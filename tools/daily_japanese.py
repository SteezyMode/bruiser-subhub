#!/usr/bin/env python3
"""Daily household EN -> JA subtitle intake. NOT a translation experiment.

Discovers English-audio movies/episodes with no existing Japanese subtitles,
uses a labeled English .srt sidecar or safely extracts an embedded English text
track, then imports a small, bounded batch into the EXISTING SubHub 1.0 queue.

Default is read-only preview. --apply explicitly stages verified sources into
the existing SQLite queue; --start also invokes the already-installed SubHub
worker in detached translate+publish mode. Existing JA, media and old jobs
are never changed or replaced. No model calls from this program.
"""
from __future__ import annotations

import argparse
from collections import Counter
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

HOST_CODE=Path.home()/'bruiser-pilot/subhub1'
if HOST_CODE.is_dir():
    sys.path.insert(0,str(HOST_CODE))
import service

VIDEO={'.mkv','.mp4','.m4v','.avi','.mov','.webm','.ts','.m2ts','.mpg','.mpeg'}
SUBS={'.srt','.ass','.ssa','.vtt','.sub','.sup'}
EN={'en','eng','english'}
JA={'ja','jp','jpn','japanese'}
TEXT_CODECS={'subrip','ass','ssa','webvtt','mov_text','text','srt'}
MAX_BYTES=2_000_000
MIN_CUES=15
MAX_CUES=12000
DEFAULT_STATE=Path.home()/'bruiser-pilot/subhub1-state'
CURSOR='daily-en-ja-cursor.json'


def digest(content):
    return hashlib.sha256(content).hexdigest()


def is_regular(path):
    return path.is_file() and not path.is_symlink()


def ensure_roots(roots):
    paths=tuple(Path(x) for x in roots)
    if not paths or any(not x.is_dir() or x.is_symlink() for x in paths):
        raise RuntimeError('Media root missing or symlinked')
    if len(set(map(str,paths)))!=len(paths):
        raise RuntimeError('Duplicate media root')
    return paths


def video_files(roots):
    """Directory walk only, no media content read and no symlink traversal."""
    for root in ensure_roots(roots):
        for dirname,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=sorted(x for x in dirs
                           if not (Path(dirname)/x).is_symlink())
            for filename in sorted(files):
                path=Path(dirname)/filename
                if path.suffix.casefold() in VIDEO and is_regular(path):
                    yield path


def sidecars(video):
    """Exact video-stem matching. A different filename is NEVER assumed."""
    stem=(video.stem+'.').casefold()
    for path in video.parent.iterdir():
        if (path.name.casefold().startswith(stem)
            and path.suffix.casefold() in SUBS
            and (path.exists() or path.is_symlink())):
            yield path


def tags(path,video):
    suffix=path.name[len(video.stem)+1:].casefold()
    return {x for x in re.split(r'[.\s_\[\]()-]+',suffix) if x}


def already_ja(video):
    # Include editorial and non-SRT tracks; never overwrite, even a symlink.
    for p in sidecars(video):
        tokens=tags(p,video)
        if tokens & JA or 'editorial' in tokens:
            return True
    return False


def english_srt(video):
    matches=[]
    for candidate in sidecars(video):
        if not is_regular(candidate) or candidate.suffix.casefold()!='.srt':
            continue
        t=tags(candidate,video)
        if t & EN and not(t & JA) and 'forced' not in t:
            matches.append(candidate)
    return sorted(matches,key=lambda x:('sdh' in tags(x,video),
                                        'cc' in tags(x,video),x.name))[0] if matches else None


def probe(video,runner=subprocess.run):
    cmd=['ffprobe','-v','error',
         '-show_entries','stream=index,codec_type,codec_name:stream_tags=language:stream_disposition=default,forced',
         '-of','json',str(video)]
    result=runner(cmd,capture_output=True,timeout=25)
    if result.returncode:
        raise RuntimeError('ffprobe returned an error')
    parsed=json.loads(result.stdout)
    streams=parsed.get('streams',[])
    if not isinstance(streams,list):
        raise RuntimeError('Invalid media track metadata')
    audios=[x for x in streams if x.get('codec_type')=='audio']
    if not audios:
        return {'audio_en':False,'ja':False,'embedded_en':None}
    default=next((x for x in audios
        if x.get('disposition',{}).get('default')==1),audios[0])
    lang=str(default.get('tags',{}).get('language','')).casefold().strip()
    subs=[x for x in streams if x.get('codec_type')=='subtitle']
    has_ja=any(str(x.get('tags',{}).get('language','')).casefold().strip() in JA
               for x in subs)
    choices=[x for x in subs
             if str(x.get('tags',{}).get('language','')).casefold().strip() in EN
             and str(x.get('codec_name','')).casefold() in TEXT_CODECS
             and x.get('disposition',{}).get('forced')!=1
             and isinstance(x.get('index'),int) and x['index']>=0]
    choices.sort(key=lambda x:(x.get('disposition',{}).get('default')!=1,
                                x.get('codec_name')!='subrip',x['index']))
    return {'audio_en':lang in EN,'ja':has_ja,
            'embedded_en':choices[0]['index'] if choices else None}


def source(video,meta,runner=subprocess.run):
    """Conservative English-only text acquisition with no file writes."""
    en=english_srt(video)
    if en:
        if en.stat().st_size>MAX_BYTES:
            raise RuntimeError('English source exceeds maximum size')
        content=en.read_bytes()
        origin='named_english_srt'
    elif meta['embedded_en'] is not None:
        result=runner(['ffmpeg','-nostdin','-hide_banner','-loglevel','error',
                       '-i',str(video),'-map','0:'+str(meta['embedded_en']),
                       '-vn','-an','-c:s','srt','-f','srt','pipe:1'],
                      capture_output=True,timeout=180)
        if result.returncode:
            raise RuntimeError('Unable to extract embedded English text subtitles')
        content=result.stdout
        origin='embedded_english_text'
    else:
        raise RuntimeError('No labeled English text subtitle available')
    if not 12<len(content)<=MAX_BYTES:
        raise RuntimeError('English SRT outside safe byte limits')
    rows=service.parse_srt(content)
    # Legacy service.render_srt renumbers non-contiguous IDs, which can
    # silently shift their time correspondence. Hold instead of publishing.
    if [r[0] for r in rows]!=list(range(1,len(rows)+1)):
        raise RuntimeError('Sparse English SRT cue IDs need normalized source')
    if not MIN_CUES<=len(rows)<=MAX_CUES:
        raise RuntimeError('Unusual English subtitle cue count')
    return content,len(rows),origin


def job_id(video):
    safe=re.sub(r'[^a-z0-9]+','-',video.stem.casefold()).strip('-')[:35].strip('-')
    safe=safe if safe else 'media'
    salt=digest(str(video.resolve()).encode())[:12]
    return 'daily-'+safe+'-'+salt


def existing_jobs(root):
    path=Path(root)/'jobs.sqlite3'
    if not path.is_file() or path.is_symlink():
        return set()
    uri='file:'+str(path)+'?mode=ro'
    with sqlite3.connect(uri,uri=True,timeout=6) as cn:
        rows=cn.execute('SELECT video FROM jobs').fetchall()
    return {x[0] for x in rows}


def pending_daily(root):
    """Resume one previously queued household title before adding another.

    Never count old legacy jobs or irrecoverable holds as active daily work.
    Read the live WAL snapshot using SQLite mode=ro without DB initialization.
    """
    db=Path(root)/'jobs.sqlite3'
    if not db.is_file() or db.is_symlink():
        return None
    with sqlite3.connect('file:'+str(db)+'?mode=ro',
                         uri=True,timeout=6) as cn:
        items=cn.execute(
            "SELECT id,status FROM jobs WHERE id LIKE 'daily-%' "
            "ORDER BY created,id").fetchall()
    return next(({'id':jid,'status':status} for jid,status in items
                 if status in ('queued','translating','translated')),None)


def cursor_read(root,roots):
    path=Path(root)/CURSOR
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Unsafe daily intake cursor')
    info=json.loads(path.read_text())
    expect=[str(x) for x in roots]
    if info.get('schema')!=1 or info.get('roots')!=expect:
        raise RuntimeError('Daily intake roots changed; refuse cursor mismatch')
    value=info.get('last')
    if not isinstance(value,str):
        raise RuntimeError('Invalid daily intake cursor')
    return value


def cursor_write(root,roots,last):
    if not last:
        return
    folder=Path(root)
    folder.mkdir(parents=True,exist_ok=True)
    data={'schema':1,'roots':[str(x) for x in roots],'last':last}
    service.atomic(folder/CURSOR,
                   (json.dumps(data,sort_keys=True,indent=2)+'\n').encode())


def candidates(roots,cursor,known):
    """Rotate through complete library across runs; avoid first-folder trap."""
    paths=list(video_files(roots))
    paths.sort(key=str)
    ordered=[p for p in paths if str(p)>cursor]+[
            p for p in paths if str(p)<=cursor] if cursor else paths
    for p in ordered:
        if str(p) not in known and not already_ja(p):
            yield p


@contextlib.contextmanager
def exclusive_intake(root,old_lock=None):
    paths=[Path(root)/'run.lock',old_lock or service.OLD_WORKER_LOCK]
    handles=[]
    try:
        for p in paths:
            p.parent.mkdir(parents=True,exist_ok=True)
            h=p.open('a+b')
            handles.append(h)
            try:
                fcntl.flock(h.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('Subtitle worker already active; intake deferred') from exc
        yield
    finally:
        for handle in handles:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
            handle.close()


def next_ready(roots,root,probes=30,probe_fn=probe,source_fn=source):
    roots=ensure_roots(roots)
    cursor=cursor_read(root,roots)
    known=existing_jobs(root)
    counts=Counter()
    last=None
    chosen=None
    for vid in candidates(roots,cursor or '',known):
        if counts['probed']>=probes:
            break
        last=str(vid)
        counts['probed']+=1
        try:
            details=probe_fn(vid)
            if details['ja'] or not details['audio_en']:
                counts['existing_ja_or_nonenglish']+=1
                continue
            raw,cues,origin=source_fn(vid,details)
            stats=vid.stat()
            chosen={'video':vid,'raw':raw,'cues':cues,'origin':origin,
                    'mtime_ns':stats.st_mtime_ns,'size':stats.st_size,
                    'source_sha':digest(raw),
                    'id':job_id(vid)}
            counts['ready']+=1
            break
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,
                json.JSONDecodeError,UnicodeError):
            counts['needs_english_or_review']+=1
    return chosen,last,dict(counts)


def ensure_still_safe(record,roots,probe_fn=probe):
    video=record['video']
    if not is_regular(video):
        raise RuntimeError('Video changed or removed')
    if not any(video.resolve().is_relative_to(r.resolve()) for r in roots):
        raise RuntimeError('Video moved outside safe library roots')
    st=video.stat()
    if st.st_size!=record['size'] or st.st_mtime_ns!=record['mtime_ns']:
        raise RuntimeError('Video changed during daily scan')
    if already_ja(video):
        raise RuntimeError('Japanese subtitles appeared during scan')
    details=probe_fn(video)
    if not details['audio_en'] or details['ja']:
        raise RuntimeError('English audio or Japanese subtitle state changed')
    if digest(record['raw'])!=record['source_sha']:
        raise RuntimeError('Staged English source changed')


def queue_one(record,roots,root,probe_fn=probe):
    ensure_still_safe(record,roots,probe_fn)
    with exclusive_intake(root):
        # Recheck before beginning the transaction. Do not duplicate a
        # movie already scheduled under a DIFFERENT job name.
        if str(record['video']) in existing_jobs(root):
            return False
        store=service.Store(root)
        try:
            # Enforce the installed service's canonical media-root policy too.
            service.secure_video(record['video'])
            return store.add(record['id'],record['video'],record['raw'],
                             'eng',scope='daily',priority=-20)
        finally:
            store.cn.close()


def start_worker(root,job,worker=None,launcher=None):
    """Start ONLY the selected job, never the other legacy queued titles.

    This is a tiny isolated wrapper around installed main.run(), not a new
    translation engine. The child keeps its own two worker locks and thermal
    safeguards. Never claim publication until status says published.
    """
    import subprocess as sp
    worker=Path(worker or Path(__file__).with_name('daily_worker.py'))
    if worker.is_symlink() or not worker.is_file():
        raise RuntimeError('Daily single-title worker missing; job remains queued')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,100}',job):
        raise RuntimeError('Unsafe queued daily job ID')
    log=Path(root)/'daily-worker.log'
    with log.open('a',encoding='utf8') as out:
        out.write('\n=== '+service.stamp()+'; job '+job+' ===\n')
        out.flush()
        command=[sys.executable,str(worker),
                 '--root',str(root),'--job-id',job]
        if launcher is None:
            p=sp.Popen(command,stdin=sp.DEVNULL,stdout=out,stderr=sp.STDOUT,
                       start_new_session=True,cwd=str(worker.parent))
        else:
            p=launcher(command,out)
    return 'STARTED daily single-title PID '+str(p.pid)+' log '+str(log)


def daily(roots=service.SOURCE_ROOTS,root=DEFAULT_STATE,
          apply=False,start=False,probes=30,
          probe_fn=probe,source_fn=source,worker=None,
          launcher=None):
    roots=ensure_roots(roots)
    if not 1<=probes<=200: raise ValueError('Probe budget must be 1..200')
    if start and not apply:raise ValueError('--start requires --apply')
    pending=pending_daily(root)
    if pending:
        print('DAILY_PENDING',pending['id'],pending['status'],
              'continuing_existing_title_first',flush=True)
        if not apply:
            print('DAILY_RESULT preview_existing_job__no_changes',flush=True)
            return 'pending_preview'
        if start:
            print('DAILY_WORKER',start_worker(root,pending['id'],worker,launcher),
                  flush=True)
            print('DAILY_RESULT existing_job_resumed__not_yet_published',flush=True)
            return 'resumed'
        print('DAILY_RESULT existing_job_pending__no_new_title',flush=True)
        return 'pending'
    candidate,last,counts=next_ready(roots,root,probes,probe_fn,source_fn)
    print('DAILY_SCAN',json.dumps(counts,sort_keys=True),flush=True)
    if candidate is None:
        if apply:cursor_write(root,roots,last)
        print('DAILY_RESULT no_eligible_english_source_in_this_scan',flush=True)
        return 'no_ready'
    print('DAILY_CANDIDATE',candidate['video'].name,
          candidate['cues'],'English cues',
          candidate['origin'],flush=True)
    if not apply:
        print('DAILY_RESULT preview_only__nothing_queued_or_translated',flush=True)
        return 'preview'
    added=queue_one(candidate,roots,root,probe_fn)
    cursor_write(root,roots,last)
    if not added:
        print('DAILY_RESULT already_queued',flush=True)
        return 'already_queued'
    print('DAILY_QUEUED',candidate['id'],
          'existing_SubHub_1.0_job',flush=True)
    if start:
        result=start_worker(root,candidate['id'],worker,launcher)
        print('DAILY_WORKER',result,flush=True)
        print('DAILY_RESULT queued_and_worker_started__not_yet_published',flush=True)
        return 'started'
    print('DAILY_RESULT queued__not_started',flush=True)
    return 'queued'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=DEFAULT_STATE)
    parser.add_argument('--media-root',type=Path,action='append',default=None)
    parser.add_argument('--probe-budget',type=int,default=30)
    parser.add_argument('--apply',action='store_true',
                        help='Queue at most ONE verified title in existing SubHub 1.0')
    parser.add_argument('--start',action='store_true',
                        help='Also start installed worker in detached translate/publish mode')
    args=parser.parse_args(argv)
    try:
        daily(roots=args.media_root or service.SOURCE_ROOTS,root=args.root,
              apply=args.apply,start=args.start,probes=args.probe_budget)
    except Exception as exc:
        # No full private media paths in output.
        print('DAILY_BLOCKED',type(exc).__name__,
              str(exc)[:150] if isinstance(exc,(ValueError,RuntimeError))
              else '',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
