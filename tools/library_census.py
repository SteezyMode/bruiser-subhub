#!/usr/bin/env python3
"""Read-only census of local video files and available EN/JA subtitle sources.

Pure discovery: no import, model call, OCR, subtitle acquisition, publishing,
database write or media mutation. A full per-file manifest is private and only
created with --out; default output is aggregate counts.
"""
from __future__ import annotations
import argparse
from collections import Counter
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys

VIDEO={'.mkv','.mp4','.m4v','.avi','.mov','.webm','.ts','.m2ts','.mpg','.mpeg','.wmv'}
SUBS={'.srt','.ass','.ssa','.vtt','.sub','.sup'}
EN={'en','eng','english'}
JA={'ja','jp','jpn','japanese'}
TEXT_CODECS={'subrip','ass','ssa','webvtt','mov_text','text','srt','microdvd','sami'}
IMAGE_CODECS={'hdmv_pgs_subtitle','dvd_subtitle','dvb_subtitle','xsub'}
STATUSES=('existing_ja_sidecar','existing_ja_embedded','needs_metadata_review',
          'audio_not_verified_english','ready_english_text','needs_english_ocr',
          'needs_english_source')


def sidecar_languages(video, siblings):
    """Conservative match: this exact video stem followed by a language suffix.

    Never infer a language from untagged sidecars or from the movie's own title.
    Tracks with non-matching naming conventions remain unverified.
    """
    prefix=video.stem.casefold()+'.'
    found=set()
    for sibling in siblings:
        if sibling.is_symlink() or not sibling.is_file() or sibling.suffix.casefold() not in SUBS:
            continue
        name=sibling.name.casefold()
        if not name.startswith(prefix):
            continue
        words=name[len(prefix):].replace('_','.').replace('-','.').split('.')
        if any(token in JA for token in words):found.add('ja')
        if any(token in EN for token in words):found.add('en')
    return found


def probe(video,timeout=12):
    """Only ffprobe the container's metadata. Never decode/copy/transcode media."""
    cmd=['ffprobe','-v','error','-show_entries',
         'stream=codec_type,codec_name:stream_tags=language:stream_disposition=default',
         '-of','json',str(video)]
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
        if p.returncode!=0:raise ValueError('ffprobe failed')
        streams=json.loads(p.stdout).get('streams',[])
        if not isinstance(streams,list):raise ValueError('Invalid ffprobe streams')
        audio=[x for x in streams if x.get('codec_type')=='audio']
        main=next((x for x in audio if x.get('disposition',{}).get('default')==1),
                  audio[0] if audio else {})
        lang=str(main.get('tags',{}).get('language','')).casefold()
        audio_en=lang in EN
        subs=[x for x in streams if x.get('codec_type')=='subtitle']
        ja=any(str(x.get('tags',{}).get('language','')).casefold() in JA for x in subs)
        en=[x for x in subs if str(x.get('tags',{}).get('language','')).casefold() in EN]
        en_text=any(str(x.get('codec_name','')).casefold() in TEXT_CODECS for x in en)
        en_image=any(str(x.get('codec_name','')).casefold() in IMAGE_CODECS for x in en)
        en_unknown=bool(en and not(en_text or en_image))
        return {'ok':True,'audio_lang':lang or 'unknown','audio_en':audio_en,
                'ja':ja,'en_text':en_text,'en_image':en_image,
                'en_unknown_codec':en_unknown}
    except (OSError,ValueError,subprocess.TimeoutExpired,json.JSONDecodeError):
        return {'ok':False,'audio_lang':'unverified','audio_en':False,
                'ja':False,'en_text':False,'en_image':False,'en_unknown_codec':False}


def classify(sidecar,metadata):
    """Never mark a film ready if the English audio language is unverified."""
    if 'ja' in sidecar:return 'existing_ja_sidecar'
    if metadata['ok'] and metadata['ja']:return 'existing_ja_embedded'
    if not metadata['ok']:return 'needs_metadata_review'
    if not metadata['audio_en']:return 'audio_not_verified_english'
    if 'en' in sidecar or metadata['en_text']:return 'ready_english_text'
    if metadata['en_image'] or metadata['en_unknown_codec']:return 'needs_english_ocr'
    return 'needs_english_source'


def enumerate_videos(roots):
    for root in roots:
        base=Path(root)
        if base.is_symlink() or not base.is_dir():
            raise ValueError('Media root missing, symlinked or not a directory: '+str(root))
        for dirname, dirs, names in os.walk(base,followlinks=False):
            dirs[:]=sorted(x for x in dirs if not (Path(dirname)/x).is_symlink())
            siblings=[Path(dirname)/x for x in names]
            for item in sorted(siblings):
                if item.is_symlink() or item.suffix.casefold() not in VIDEO:
                    continue
                try:
                    size=item.stat().st_size
                except OSError:
                    continue
                if item.is_file():
                    yield item,size,siblings


def census(roots,lim=0,probe_fn=probe,progress=None):
    entries=[]; counts=Counter();bytes_total=0
    for video,size,siblings in enumerate_videos(roots):
        if lim and len(entries)>=lim:break
        sidecar=sidecar_languages(video,siblings)
        meta=probe_fn(video)
        status=classify(sidecar,meta)
        entries.append({'path':str(video),'size_bytes':size,'status':status,
                        'en_sidecar':'en' in sidecar,'ja_sidecar':'ja' in sidecar,
                        'en_embedded_text':meta['en_text'],'en_embedded_bitmap':meta['en_image'],
                        'ja_embedded':meta['ja'],'audio_lang':meta['audio_lang'],
                        'probe_ok':meta['ok']})
        counts[status]+=1;bytes_total+=size
        if progress and len(entries)%250==0:progress(len(entries))
    return {'version':1,'scanned_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'roots':[str(Path(x)) for x in roots],
            'total_videos':len(entries),'total_bytes':bytes_total,
            'status_counts':{key:counts[key] for key in STATUSES},
            'videos':entries}


def save_private(output,data):
    payload=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as out:
        out.write(payload);out.flush();os.fsync(out.fileno())


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,action='append',required=True,
                    help='One or more media-library directories (repeat for each root)')
    ap.add_argument('--limit',type=int,default=0,help='Optional number of videos for a small pilot; 0=all')
    ap.add_argument('--out',type=Path,
                    help='OPTIONAL private per-file JSON; refused if output already exists')
    ap.add_argument('--probe-timeout',type=int,default=12)
    args=ap.parse_args(argv)
    if args.limit<0 or args.probe_timeout<1:ap.error('Invalid --limit/--probe-timeout')
    try:
        data=census(args.root,args.limit,
                    probe_fn=lambda v:probe(v,args.probe_timeout),
                    progress=lambda n:print(f'Inspected {n} video headers...',file=sys.stderr,flush=True))
        print(f"READ-ONLY CENSUS: {data['total_videos']} videos, "
              f"{data['total_bytes']/10**12:.2f} TB of video files")
        for name,count in data['status_counts'].items():
            print(f'  {name}: {count}')
        print('Existing JA tracks may still need quality review; subtitles with unrecognized '
              'filenames/language metadata may be missed.')
        print('Ready-for-translation is a candidate count, NOT a queued job or verified EN source.')
        if args.out:
            save_private(args.out,data)
            print('PRIVATE manifest:',args.out)
        else:
            print('No manifest written. No video, subtitle, database or model changed.')
    except (OSError,ValueError) as exc:
        ap.error(str(exc))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
