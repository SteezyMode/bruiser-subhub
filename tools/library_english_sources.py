#!/usr/bin/env python3
"""Incremental library-wide EN subtitle inventory + strict Jellyfin hash downloads.

English *source acquisition* ONLY. No machine translation, no full-library
Jellyfin scheduled-task mutation, no Sublarr, no media moves/overwrites.

Initial: scan all Jellyfin Movies/Episodes in approved host roots, reusing
unchanged ffprobe results. Fill: search existing Jellyfin subtitle providers
for a small budget of missing-EN items, automatically POST only genuine
IsHashMatch=true English SRTs. Prioritize American Dad S08 but index all.

Persistent private SQLite records failed searches + next retry time, so
repeated calls proceed through the library rather than hammering providers.
"""
from __future__ import annotations

import argparse
from collections import Counter
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

try:
    import daily_japanese as intake
    import jellyfin_english_sources as jf
    import american_dad_seasons as seasons
except ModuleNotFoundError:
    from tools import daily_japanese as intake
    from tools import jellyfin_english_sources as jf
    from tools import american_dad_seasons as seasons

STATE=Path.home()/'bruiser-pilot/english-source-inventory'
PAGE_SIZE=200
MAX_PAGES=250
SOURCE_TYPES={'Episode','Movie'}
EN={'en','eng','english'}
JA={'ja','jp','jpn','japanese'}
SUB_TEXT={'.srt','.ass','.ssa','.vtt'}
RECHECK_S=7*86400
ERROR_RETRY_S=86400
PRIORITY=re.compile(r'american[\W_]*dad',re.I)
S08=re.compile(r'(?<![a-z0-9])s08[\s._-]*e\d{1,3}(?!\d)',re.I)
ID=re.compile(r'[A-Za-z0-9_-]{4,80}\Z')
SAFE_STATUSES={'missing','no_hash_match','provider_error','jellyfin_only'}


@contextlib.contextmanager
def lock(state):
    state=Path(state)
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    if state.is_symlink():
        raise RuntimeError('Inventory state directory must not be symlinked')
    p=state/'scan.lock'
    if p.is_symlink():
        raise RuntimeError('Unsafe inventory lock path')
    with p.open('a+b') as fd:
        try:
            fcntl.flock(fd.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another English inventory operation is running') from exc
        try:yield
        finally:fcntl.flock(fd.fileno(),fcntl.LOCK_UN)


@contextlib.contextmanager
def database(state):
    state=Path(state)
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    if state.is_symlink():
        raise RuntimeError('Unsafe inventory state')
    path=state/'catalog.sqlite3'
    if path.is_symlink():
        raise RuntimeError('Unsafe inventory SQLite path')
    with sqlite3.connect(path,timeout=30) as cn:
        cn.row_factory=sqlite3.Row
        cn.execute('PRAGMA busy_timeout=30000')
        cn.execute('''CREATE TABLE IF NOT EXISTS media(
            path TEXT PRIMARY KEY,
            jellyfin_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            title TEXT NOT NULL,
            series TEXT NOT NULL,
            season INTEGER,
            episode INTEGER,
            fingerprint TEXT NOT NULL,
            state TEXT NOT NULL,
            audio_lang TEXT NOT NULL,
            priority INTEGER NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_search INTEGER NOT NULL DEFAULT 0,
            last_result TEXT NOT NULL DEFAULT '',
            scanned_at INTEGER NOT NULL,
            last_seen INTEGER NOT NULL
        )''')
        cn.execute('CREATE INDEX IF NOT EXISTS media_search ON media(state,next_search,priority)')
        yield cn


def catalog(client):
    """Jellyfin library-wide actual Movie + Episode items. Never filesystem crawl."""
    found={}
    for page in range(MAX_PAGES):
        query=urlencode({
            'Recursive':'true',
            'IncludeItemTypes':'Movie,Episode',
            'Fields':'Path,MediaStreams',
            'StartIndex':page*PAGE_SIZE,
            'Limit':PAGE_SIZE
        })
        response=client.get('/Items?'+query)
        if not isinstance(response,dict) or not isinstance(response.get('Items'),list):
            raise RuntimeError('Jellyfin catalog returned an invalid response')
        items=response['Items']
        for x in items:
            if (x.get('Type') in SOURCE_TYPES and x.get('Id') and
                isinstance(x.get('Path'),str)):
                found.setdefault(x['Path'],x)
        if (len(items)<PAGE_SIZE or
            isinstance(response.get('TotalRecordCount'),int) and
            (page+1)*PAGE_SIZE>=response['TotalRecordCount']):
            return found
    raise RuntimeError('Jellyfin catalog exceeds bounded pagination')


def get_video(item,roots):
    path=Path(item['Path'])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        return None
    real=path.resolve()
    if not any(real.is_relative_to(root.resolve()) for root in roots):
        return None
    return path


def english_sidecar(video):
    """Any safely named existing English dialogue file, not just plain SRT."""
    for path in intake.sidecars(video):
        if (path.suffix.casefold() in SUB_TEXT and
            (intake.tags(path,video)&EN) and
            'forced' not in intake.tags(path,video) and
            path.is_file() and not path.is_symlink()):
            return True
    return False


def sidecar_fingerprint(video):
    data=[]
    for path in sorted(intake.sidecars(video),key=str):
        try:
            st=path.lstat()
            data.append((path.name,st.st_size,st.st_mtime_ns,st.st_mode))
        except OSError:
            data.append((path.name,'missing'))
    st=video.stat()
    return hashlib.sha256(json.dumps(
        (st.st_size,st.st_mtime_ns,data),
        ensure_ascii=False,sort_keys=True).encode('utf8')).hexdigest()


def item_streams(item):
    streams=item.get('MediaStreams')
    if not isinstance(streams,list):
        return None
    langs=[]
    ja_found=False
    audio=None
    for x in streams:
        if not isinstance(x,dict):continue
        lang=str(x.get('Language') or '').strip().casefold()
        if x.get('Type')=='Audio' and (
                audio is None or x.get('IsDefault') is True):
            audio=lang
        if (x.get('Type')=='Subtitle' and lang in JA and
                not x.get('IsForced')):
            ja_found=True
        if (x.get('Type')=='Subtitle' and lang in EN and
            not x.get('IsForced') and
            str(x.get('Codec') or '').casefold() in
                {'subrip','srt','ass','ssa','webvtt','mov_text','text'}):
            langs.append('en')
    return {'has_en_text':bool(langs),'has_ja':ja_found,
            'audio_lang':audio or 'unknown'}


def inspect(video,item,probe_fn=intake.probe):
    side=english_sidecar(video)
    stream=item_streams(item)
    if stream is None:
        probe=probe_fn(video)
        stream={'has_en_text':probe.get('embedded_en') is not None,
                'has_ja':bool(probe.get('ja')),
                'audio_lang':'en' if probe.get('audio_en') else 'unknown'}
    if intake.already_ja(video) or stream['has_ja']:
        return 'japanese_present',stream['audio_lang']
    return ('ready' if side or stream['has_en_text'] else 'missing',
            stream['audio_lang'])


def ordering(video,item):
    if PRIORITY.search(str(video)) and S08.search(video.name):
        return 0
    if item.get('Type')=='Episode':
        return 10
    return 20


def scan(client,roots,state=STATE,probe_fn=intake.probe,
         now=None,catalog_fn=catalog,log=print):
    """Full initial scan; repeat passes reuse unchanged per-file metadata."""
    roots=intake.ensure_roots(roots)
    now=int(now if now is not None else time.time())
    raw=catalog_fn(client)
    counts=Counter()
    seen=set()
    committed=0
    with lock(state),database(state) as db:
        for _path,item in raw.items():
            video=get_video(item,roots)
            if not video:
                counts['out_of_scope_or_missing']+=1
                continue
            path=str(video.resolve())
            if path in seen:
                counts['duplicate_path']+=1
                continue
            seen.add(path)
            item_id=str(item['Id'])
            if not ID.fullmatch(item_id):
                counts['invalid_jellyfin_id']+=1
                continue
            fingerprint=sidecar_fingerprint(video)
            old=db.execute('SELECT * FROM media WHERE path=?',(path,)).fetchone()
            if old and old['fingerprint']==fingerprint:
                status=('japanese_present' if (intake.already_ja(video)
                    or (item_streams(item) or {}).get('has_ja'))
                    else old['state'])
                # When provider search previously found no hash result,
                # preserve that status while the file is unchanged.
                if status not in SAFE_STATUSES and status!='ready':
                    status='missing'
                audio=old['audio_lang']
                counts['cached']+=1
            else:
                try:
                    status,audio=inspect(video,item,probe_fn)
                except (OSError,RuntimeError,ValueError):
                    counts['metadata_error']+=1
                    continue
                counts['refreshed']+=1
            season=item.get('ParentIndexNumber')
            episode=item.get('IndexNumber')
            if not isinstance(season,int) or season<0:season=None
            if not isinstance(episode,int) or episode<0:episode=None
            new=old is None or old['fingerprint']!=fingerprint
            # Retry only if still missing. Every file modification resets its
            # cooldown, but old search results are preserved for unchanged media.
            db.execute('''INSERT INTO media(
                path,jellyfin_id,media_type,title,series,season,episode,
                fingerprint,state,audio_lang,priority,attempt_count,
                next_search,last_result,scanned_at,last_seen)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                  jellyfin_id=excluded.jellyfin_id,
                  media_type=excluded.media_type,title=excluded.title,
                  series=excluded.series,season=excluded.season,
                  episode=excluded.episode,fingerprint=excluded.fingerprint,
                  state=CASE WHEN excluded.fingerprint!=media.fingerprint
                    THEN excluded.state ELSE media.state END,
                  audio_lang=excluded.audio_lang,priority=excluded.priority,
                  attempt_count=CASE WHEN excluded.fingerprint!=media.fingerprint
                    THEN 0 ELSE media.attempt_count END,
                  next_search=CASE WHEN excluded.fingerprint!=media.fingerprint
                    THEN 0 ELSE media.next_search END,
                  last_result=CASE WHEN excluded.fingerprint!=media.fingerprint
                    THEN '' ELSE media.last_result END,
                  scanned_at=excluded.scanned_at,last_seen=excluded.last_seen''',
                (path,item_id,item['Type'],str(item.get('Name') or ''),
                 str(item.get('SeriesName') or ''),season,episode,
                 fingerprint,status,audio,ordering(video,item),
                 0 if new else old['attempt_count'],
                 0 if new else old['next_search'],
                 '' if new else old['last_result'],now,now))
            counts[status]+=1
            committed+=1
            # Persist progress in batches. A dropped SSH connection should not
            # force a multi-thousand-title ffprobe pass to restart from zero.
            if committed%100==0:
                db.commit()
                log('EN_INVENTORY_PROGRESS','catalog_items',committed,
                    'cached',counts['cached'],'missing',counts['missing'])
        # Keep history for absent Jellyfin paths, but never search them.
        counts['catalog_eligible_paths']=len(seen)
        counts['jellyfin_items']=len(raw)
        db.commit()
    log('EN_INVENTORY',json.dumps(dict(sorted(counts.items())),
                                  sort_keys=True))
    return dict(counts)


def verify_identity(video,row):
    """Do not search wrong show/episode metadata for differently numbered shows."""
    if row['media_type']=='Episode':
        tag=seasons.SXXEXX.search(video.name) or seasons.XXxYY.search(video.name)
        if tag and row['season'] is not None and row['episode'] is not None:
            if (int(tag[1]),int(tag[2]))!=(row['season'],row['episode']):
                return False
    return True


def hash_match(subtitle,row):
    """ONLY a true Jellyfin provider video-file hash match auto-downloads."""
    if subtitle.get('IsHashMatch') is not True:
        return False
    if str(subtitle.get('Format','')).casefold() not in jf.VALID_FORMAT:
        return False
    if str(subtitle.get('ThreeLetterISOLanguageName','')).casefold() not in EN:
        return False
    if (not subtitle.get('Id') or not subtitle.get('ProviderName') or
        subtitle.get('IsForced') is True):
        return False
    # A hash match is authoritative, but refuse explicit contradictory
    # season/episode tags that could indicate provider catalog corruption.
    if row['media_type']=='Episode':
        name=str(subtitle.get('Name') or '')
        tag=seasons.SXXEXX.search(name) or seasons.XXxYY.search(name)
        if tag and row['season'] is not None and row['episode'] is not None:
            if (int(tag[1]),int(tag[2]))!=(row['season'],row['episode']):
                return False
    return True


def choose(results,row):
    if not isinstance(results,list):
        raise RuntimeError('Jellyfin subtitle search returned non-list')
    matches=[r for r in results if isinstance(r,dict) and hash_match(r,row)]
    matches.sort(key=lambda x:(-int(x.get('DownloadCount') or 0),
                               -float(x.get('CommunityRating') or 0),
                               str(x.get('ProviderName') or '')))
    return matches[0] if matches else None


def _update(db,row,now,state,detail,delay):
    db.execute('''UPDATE media SET state=?,last_result=?,
      attempt_count=attempt_count+1,next_search=?,scanned_at=?
      WHERE path=?''',(state,detail,now+delay,now,row['path']))
    db.commit()


def fill(client,roots,state=STATE,search_budget=10,now=None,
         log=print,probe_fn=intake.probe):
    """One bounded provider pass; never contacts providers on inventory scan.

    Each miss receives a 7-day cooldown; errors receive 1 day. Repeating
    the command moves to the next candidate, not the same top-of-list item.
    """
    if not 1<=search_budget<=30:
        raise ValueError('Provider search budget must be 1..30')
    roots=intake.ensure_roots(roots)
    now=int(now if now is not None else time.time())
    counts=Counter()
    with lock(state),database(state) as db:
        rows=db.execute('''SELECT * FROM media
             WHERE state IN ('missing','no_hash_match','provider_error')
               AND next_search<=?
             ORDER BY priority,attempt_count,path LIMIT ?''',
             (now,search_budget)).fetchall()
        for row in rows:
            video=Path(row['path'])
            # Never submit an unapproved/path-escaped file to provider APIs.
            if (not video.is_file() or video.is_symlink() or
                not any(video.resolve().is_relative_to(p.resolve()) for p in roots)):
                _update(db,row,now,'out_of_scope','media_missing_or_moved',RECHECK_S)
                counts['out_of_scope']+=1
                continue
            try:
                if intake.already_ja(video):
                    _update(db,row,now,'japanese_present',
                            'japanese_already_available',0)
                    counts['japanese_present']+=1
                    continue
                if sidecar_fingerprint(video)!=row['fingerprint']:
                    _update(db,row,now,'stale','rescan_before_search',0)
                    counts['stale']+=1
                    continue
                if english_sidecar(video):
                    _update(db,row,now,'ready','existing_english',0)
                    counts['already_ready']+=1
                    continue
                if not verify_identity(video,row):
                    _update(db,row,now,'numbering_conflict',
                            'jellyfin_metadata_mismatch',RECHECK_S)
                    counts['numbering_conflict']+=1
                    continue
                route=('/Items/'+quote(row['jellyfin_id'],safe='')+
                       '/RemoteSearch/Subtitles/eng')
                results=client.get(route)
                subtitle=choose(results,row)
                if not subtitle:
                    _update(db,row,now,'no_hash_match','no_perfect_provider_match',
                            RECHECK_S)
                    counts['no_hash_match']+=1
                    log('EN_FILL',row['media_type'],'no_perfect_match')
                    continue
                client.post('/Items/'+quote(row['jellyfin_id'],safe='')+
                            '/RemoteSearch/Subtitles/'+quote(str(subtitle['Id']),safe=''))
                # Jellyfin sometimes saves to internal metadata. Only a sidecar
                # works with the existing SubHub translator. Verify reality.
                src=intake.english_srt(video)
                if src:
                    try:
                        raw,n,origin=intake.source(video,{
                            'embedded_en':None},runner=None)
                    except (OSError,RuntimeError,ValueError,UnicodeError) as e:
                        _update(db,row,now,'provider_error',
                                'download_not_usable_srt',ERROR_RETRY_S)
                        counts['invalid_srt']+=1
                        continue
                    _update(db,row,now,'ready','downloaded_verified_english_srt',0)
                    counts['downloaded']+=1
                    log('EN_FILL',row['media_type'],'ready',
                        'cues',n,'priority',row['priority'])
                else:
                    _update(db,row,now,'jellyfin_only',
                            'provider_download_no_external_srt',RECHECK_S)
                    counts['jellyfin_only']+=1
                    log('EN_FILL',row['media_type'],'saved_internal_or_missing_srt')
            except (HTTPError,URLError,OSError,TimeoutError,RuntimeError,ValueError) as e:
                # Rate limits are a hard stop for this pass: no spray of
                # additional requests against an exhausted provider.
                code=e.code if isinstance(e,HTTPError) else None
                _update(db,row,now,'provider_error',
                        'http_'+str(code) if code else type(e).__name__,
                        RECHECK_S if code==429 else ERROR_RETRY_S)
                counts['provider_error']+=1
                if code in (429,503):
                    counts['rate_limited_or_unavailable']+=1
                    break
    result={'attempted':sum(counts.get(k,0) for k in
              ('no_hash_match','downloaded','jellyfin_only',
               'invalid_srt','provider_error')),
            'outcomes':dict(sorted(counts.items()))}
    log('EN_FILL_SUMMARY',json.dumps(result,sort_keys=True))
    return result


def report(state=STATE,log=print):
    with database(state) as db:
        groups=db.execute('SELECT state,COUNT(*) FROM media GROUP BY state').fetchall()
        counts={str(x[0]):x[1] for x in groups}
        priority=db.execute('''SELECT state,COUNT(*) FROM media WHERE priority=0
                                GROUP BY state''').fetchall()
        p={str(x[0]):x[1] for x in priority}
    data={'total':sum(counts.values()),'states':counts,'american_dad_s08':p}
    log('EN_STATUS',json.dumps(data,sort_keys=True))
    return data


def cli(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('scan','fill','run','status'))
    p.add_argument('--state',type=Path,default=STATE)
    p.add_argument('--budget',type=int,default=10)
    args=p.parse_args(argv)
    try:
        if args.action=='status':
            report(args.state)
            return 0
        client=jf.Jellyfin()
        auth=jf.authenticate(client)
        print('JELLYFIN_AUTH',auth,flush=True)
        if args.action in ('scan','run'):
            scan(client,intake.service.SOURCE_ROOTS,args.state)
        if args.action in ('fill','run'):
            fill(client,intake.service.SOURCE_ROOTS,args.state,args.budget)
        if args.action!='status':
            report(args.state)
    except Exception as exc:
        # Error strings may hold tokens, paths or private dialog: types only.
        print('EN_INVENTORY_BLOCKED',type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    os.umask(0o077)
    raise SystemExit(cli())
