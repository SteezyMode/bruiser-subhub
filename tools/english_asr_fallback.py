#!/usr/bin/env python3
"""Local-only English speech transcription, one American Dad episode at a time.

This is a source fallback when subtitle providers cannot identify the release.
It does NOT translate, call Ollama, touch Jellyfin settings, or upload audio.
Uses CPU-only faster-whisper to keep the RTX 3050 available for existing jobs.
Produces a clearly labeled source: VIDEO.Bruiser-ASR.en.srt, create-only.

Requires isolated faster-whisper venv prepared by the installer. All model
weights download into a private owner cache; actual audio stays on this host.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import time

try:
    import daily_japanese as intake
    import american_dad_seasons as seasons
except ModuleNotFoundError:
    from tools import daily_japanese as intake
    from tools import american_dad_seasons as seasons

MODEL='small.en'
CPU_THREADS=3
MIN_CUES=50
MAX_CUES=1500
MIN_LENGTH=600
MAX_LENGTH=2700
STATE=Path.home()/'bruiser-pilot/american-dad-asr-state'
MODEL_CACHE=STATE/'models'


def audio_source(video,runner=subprocess.run):
    """Return (primary English audio stream absolute index,duration seconds)."""
    result=runner(['ffprobe','-v','error',
        '-show_entries','stream=index,codec_type:stream_tags=language:stream_disposition=default',
        '-of','json',str(video)],
        capture_output=True,text=True,timeout=30)
    if result.returncode:
        raise RuntimeError('Unable to inspect video audio streams')
    streams=json.loads(result.stdout).get('streams',[])
    tracks=[s for s in streams if s.get('codec_type')=='audio']
    if not tracks:
        raise ValueError('Video has no audio')
    default=next((s for s in tracks
             if s.get('disposition',{}).get('default')==1),tracks[0])
    lang=str(default.get('tags',{}).get('language','')).casefold().strip()
    if lang not in intake.EN:
        raise ValueError('Primary audio not explicitly labeled English')
    idx=default.get('index')
    if not isinstance(idx,int) or idx<0:
        raise ValueError('Invalid primary English stream index')
    length=runner(['ffprobe','-v','error',
        '-show_entries','format=duration',
        '-of','default=noprint_wrappers=1:nokey=1',str(video)],
        capture_output=True,text=True,timeout=30)
    if length.returncode:
        raise RuntimeError('Cannot determine video length')
    seconds=float(length.stdout.strip())
    if not math.isfinite(seconds) or not MIN_LENGTH<=seconds<=MAX_LENGTH:
        raise ValueError('Only normal TV-episode durations are supported')
    return idx,seconds


def fmt(ms):
    ms=max(0,int(ms))
    h,rem=divmod(ms,3_600_000)
    m,rem=divmod(rem,60_000)
    s,millis=divmod(rem,1000)
    return f'{h:02d}:{m:02d}:{s:02d},{millis:03d}'


def cues_from_segments(segments,duration):
    """Reflow timed Whisper words into readable short cues; no timing drift."""
    words=[]
    for segment in segments:
        part=getattr(segment,'words',None)
        if part:
            for word in part:
                start=getattr(word,'start',None)
                end=getattr(word,'end',None)
                value=str(getattr(word,'word','') or '').strip()
                if (not value or start is None or end is None or
                    not math.isfinite(float(start)) or
                    not math.isfinite(float(end)) or
                    float(start)<0 or float(end)<=float(start)):
                    continue
                words.append((float(start),float(end),value))
        else:
            text=str(getattr(segment,'text','') or '').strip()
            start=getattr(segment,'start',None)
            end=getattr(segment,'end',None)
            if text and start is not None and end is not None:
                words.append((float(start),float(end),text))
    words.sort(key=lambda x:(x[0],x[1]))
    groups=[]
    current=[]
    def flush():
        if not current:return
        start=current[0][0]
        end=current[-1][1]
        value=' '.join(x[2] for x in current).strip()
        value=re.sub(r'\s+',' ',value)
        if value:
            groups.append((start,end,value))
        current.clear()
    for word in words:
        if word[0]>=duration or word[1]>duration+2:
            continue
        if current and (
            word[0]-current[-1][1]>1.0 or
            word[1]-current[0][0]>5.0 or
            len(' '.join([w[2] for w in current]+[word[2]]))>75):
            flush()
        current.append(word)
    flush()
    rows=[]
    previous=0
    for start,end,value in groups:
        a=max(previous,round(start*1000))
        b=min(int(duration*1000),max(a+200,round(end*1000)))
        if b<=a or b-a>30_000 or a>=duration*1000:
            continue
        if re.fullmatch(r'[.?!,\-\s]+',value):
            continue
        text='\n'.join(textwrap.wrap(value,width=42,
                                    break_long_words=False,
                                    break_on_hyphens=False))
        if not text or len(text)>240:continue
        rows.append((a,b,text))
        previous=b
    return rows


def render(rows):
    if not MIN_CUES<=len(rows)<=MAX_CUES:
        raise ValueError('Transcribed dialogue density outside expected bounds')
    lines=[]
    for index,(a,b,value) in enumerate(rows,1):
        lines.append(f'{index}\n{fmt(a)} --> {fmt(b)}\n{value}')
    out=('\n\n'.join(lines)+'\n').encode('utf8')
    if len(out)>intake.MAX_BYTES:
        raise ValueError('Transcribed SRT is oversized')
    parsed=intake.service.parse_srt(out)
    if len(parsed)!=len(rows):
        raise RuntimeError('Transcribed SRT failed existing SubHub validation')
    return out


def source_path(video):
    return video.with_name(video.stem+'.Bruiser-ASR.en.srt')


def write_create_only(target,raw):
    """Atomic, create-only; no existing subtitle overwrite, even symlinks."""
    if target.exists() or target.is_symlink():
        return False
    fd,temp=tempfile.mkstemp(prefix='.'+target.name+'.',
                             suffix='.tmp',dir=target.parent)
    temp=Path(temp)
    try:
        with os.fdopen(fd,'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp,0o644)
        # Hardlink is atomic and fails if target appeared since precheck.
        try:os.link(temp,target,follow_symlinks=False)
        except FileExistsError:return False
        return True
    finally:
        temp.unlink(missing_ok=True)


def transcribe(video,model_loader=None,runner=subprocess.run,
               download_root=MODEL_CACHE,state=STATE,print_fn=print):
    """One eligible episode; no transcript published until full validation."""
    video=Path(video)
    intake.service.secure_video(video)
    if intake.already_ja(video):
        print_fn('ASR_SKIP','existing_japanese')
        return 'skipped_ja'
    metadata=intake.probe(video)
    if metadata.get('ja'):
        print_fn('ASR_SKIP','embedded_japanese')
        return 'skipped_ja'
    if intake.english_srt(video) or metadata.get('embedded_en') is not None:
        print_fn('ASR_SKIP','existing_english')
        return 'skipped_en'
    target=source_path(video)
    if target.exists() or target.is_symlink():
        print_fn('ASR_SKIP','existing_destination')
        return 'skipped_target'
    stream,duration=audio_source(video,runner)
    state=Path(state)
    state.mkdir(mode=0o700,parents=True,exist_ok=True)
    cache=Path(download_root)
    cache.mkdir(mode=0o700,parents=True,exist_ok=True)
    if state.is_symlink() or cache.is_symlink():
        raise RuntimeError('Unsafe private ASR state path')
    if model_loader is None:
        from faster_whisper import WhisperModel
        model_loader=WhisperModel
    model=model_loader(MODEL,device='cpu',compute_type='int8',
                       cpu_threads=CPU_THREADS,num_workers=1,
                       download_root=str(cache))
    with tempfile.TemporaryDirectory(prefix='extract-',dir=state) as folder:
        wav=Path(folder)/'episode.wav'
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','error',
             '-y','-i',str(video),'-map','0:'+str(stream),'-vn','-sn',
             '-ac','1','-ar','16000','-c:a','pcm_s16le',
             '-t',str(round(duration)+1),str(wav)]
        conversion=runner(cmd,capture_output=True,text=True,timeout=120)
        if conversion.returncode or not wav.is_file() or wav.stat().st_size<50000:
            raise RuntimeError('Failed to extract local English audio')
        print_fn('ASR_TRANSCRIBING','cpu_int8','model',MODEL,flush=True)
        segments,info=model.transcribe(
            str(wav),language='en',beam_size=4,
            vad_filter=True,word_timestamps=True,
            condition_on_previous_text=False)
        rows=cues_from_segments(segments,duration)
        if getattr(info,'language','en')!='en':
            raise RuntimeError('ASR did not transcribe as English')
        raw=render(rows)
    # Avoid a change or subtitle acquisition while transcription ran.
    intake.service.secure_video(video)
    if intake.already_ja(video) or intake.english_srt(video):
        print_fn('ASR_SKIP','subtitle_arrived_during_transcription')
        return 'skipped_race'
    if intake.probe(video).get('embedded_en') is not None:
        print_fn('ASR_SKIP','embedded_english_arrived')
        return 'skipped_race'
    success=write_create_only(target,raw)
    if not success:
        return 'skipped_race'
    print_fn('ASR_READY','draft_english_source','cues',len(rows),
             'local_only',True,flush=True)
    return 'published_en_draft'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path,required=True)
    args=p.parse_args(argv)
    try:
        transcribe(args.video)
    except Exception as exc:
        print('ASR_BLOCKED',type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    os.umask(0o077)
    raise SystemExit(main())
