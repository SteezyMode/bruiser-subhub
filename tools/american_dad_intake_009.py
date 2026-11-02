#!/usr/bin/env python3
"""American Dad pilot input: discover safe video episodes and extract English SRT.

No video or subtitle modifications. Skip episodes with JA embedded or as sidecars.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import service

ROOTS=service.SOURCE_ROOTS
VIDEO_EXT={'.mkv','.mp4','.m4v','.avi','.webm'}
EPISODE=re.compile(r'(?i)s(\d{1,2})e(\d{1,3})')
SHOW=re.compile(r'(?i)american[\s._-]*dad')
JA=re.compile(r'(?i)(^|[._\s-])(ja|jp|jpn|japanese)(?=$|[._\s-])')
EN=re.compile(r'(?i)(^|[._\s-])(en|eng|english)(?=$|[._\s-])')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pilot_path(video):
    return video.with_name(video.stem+'.Bruiser Pilot Japanese.ja.srt')


def safe_video(video,roots=ROOTS):
    return (video.is_file() and not video.is_symlink() and
            any(video.resolve().is_relative_to(Path(p).resolve()) for p in roots))


def existing_ja(video):
    prefix=video.stem.casefold()+'.'
    for candidate in video.parent.iterdir():
        label=candidate.name.casefold()
        if label.startswith(prefix):
            suffix=label[len(prefix):]
            if ('editorial' in suffix or JA.search(suffix)) and (
                suffix.endswith(('.srt','.ass','.ssa','.vtt','.sub','.sup'))
                or candidate.is_symlink()
            ):
                return True
    return False


def discover(roots=ROOTS):
    for root in roots:
        if not Path(root).is_dir():continue
        for folder,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=sorted(x for x in dirs if not (Path(folder)/x).is_symlink())
            for name in sorted(files):
                path=Path(folder)/name
                if (path.suffix.lower() in VIDEO_EXT and SHOW.search(str(path))
                    and EPISODE.search(str(path)) and safe_video(path,roots)):
                    yield path


def tracks(video,runner=subprocess.run):
    p=runner(['ffprobe','-v','error','-show_streams','-of','json',str(video)],
             capture_output=True,check=True,timeout=45)
    streams=json.loads(p.stdout).get('streams',[])
    audio=[s for s in streams if s.get('codec_type')=='audio']
    primary=next((s for s in audio if s.get('disposition',{}).get('default')==1),
                 audio[0] if audio else {})
    if str(primary.get('tags',{}).get('language','')).lower() not in ('eng','en'):
        raise ValueError('Unverified English-primary audio')
    subtitles=[s for s in streams if s.get('codec_type')=='subtitle']
    if any(str(s.get('tags',{}).get('language','')).lower() in
           ('ja','jp','jpn','japanese') for s in subtitles):
        raise ValueError('Already has embedded Japanese subtitles')
    english=[s for s in subtitles
             if str(s.get('tags',{}).get('language','')).lower() in
             ('eng','en','english') and s.get('codec_name') in
             ('subrip','ass','ssa','webvtt','mov_text','text') and
             s.get('disposition',{}).get('forced')!=1]
    english.sort(key=lambda s:(
        s.get('disposition',{}).get('default')!=1,
        s.get('codec_name')!='subrip',s.get('index',999)))
    if english:
        return {'kind':'embedded','index':int(english[0]['index'])}
    for srt in sorted(video.parent.glob(video.stem+'*.srt')):
        if srt.is_symlink() or not srt.is_file():continue
        suffix=srt.name[len(video.stem):]
        if EN.search(suffix) and not JA.search(suffix):
            return {'kind':'sidecar','path':str(srt)}
    raise ValueError('No verified English text subtitle stream or sidecar')


def extract(video,track,runner=subprocess.run):
    if track['kind']=='embedded':
        p=runner(['ffmpeg','-nostdin','-hide_banner','-loglevel','error',
                  '-i',str(video),'-map','0:'+str(track['index']),
                  '-vn','-an','-c:s','srt','-f','srt','pipe:1'],
                 capture_output=True,check=True,timeout=240)
        content=p.stdout
    elif track['kind']=='sidecar':
        path=Path(track['path'])
        if path.is_symlink() or not path.is_file() or path.parent!=video.parent:
            raise ValueError('Unsafe English SRT sidecar')
        content=path.read_bytes()
    else:
        raise ValueError('Unknown English track kind')
    if not 20<len(content)<=2_000_000:
        raise ValueError('Unusual English SRT byte length')
    rows=service.parse_srt(content)
    if not 130<=len(rows)<=1500:
        raise ValueError('Unusual cue count for a full TV episode')
    return content,rows


def catalog(roots=ROOTS,limit=5):
    if not 1<=limit<=12:raise ValueError('Trial is limited to 1..12 episodes')
    selected=[]
    seen=set()
    skips={}
    for video in discover(roots):
        if len(selected)>=limit:break
        m=EPISODE.search(str(video))
        episode='S%02dE%02d'%(int(m[1]),int(m[2]))
        if episode in seen:continue
        if existing_ja(video) or pilot_path(video).exists() or pilot_path(video).is_symlink():
            skips['already_japanese']=skips.get('already_japanese',0)+1
            continue
        try:
            source=tracks(video)
            data,rows=extract(video,source)
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            reason=(type(exc).__name__+': '+str(exc))[:120]
            skips[reason]=skips.get(reason,0)+1
            continue
        st=video.stat()
        selected.append({'episode':episode,'video':str(video),
                         'track':source,'source_sha':sha(data),
                         'raw':data,'count':len(rows),
                         'video_size':st.st_size,'video_mtime_ns':st.st_mtime_ns})
        seen.add(episode)
    return selected,skips
