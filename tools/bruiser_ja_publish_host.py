#!/usr/bin/env python3
"""Publish a screened Japanese subtitle from a read-only Sublarr Docker mount.

Run as the ordinary OptiPlex host user with Docker access; no remount, sudo,
new credentials, inference, or provider requests. Never rewrite media.

This host-side bridge is deliberately separate from the in-container screener:
first run the pinned screener in --from-staged plan mode, then publish bytes from
its already-saved corrected copy through the matching host bind mount.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

TARGET_SUFFIX = '.Bruiser Sourced Unverified.ja.srt'


def docker(args, *, input_bytes=None):
    return subprocess.run(['docker', *args], input=input_bytes, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def host_path_for_movie(mounts, container_movie):
    video = Path(container_movie)
    if not video.is_absolute() or '..' in video.parts:
        raise RuntimeError('Movie path must be absolute and traversal-free')
    matched = []
    for mount in mounts:
        if mount.get('Type') != 'bind':
            continue
        dest = Path(mount.get('Destination') or '')
        src = Path(mount.get('Source') or '')
        if not dest.is_absolute() or not src.is_absolute():
            continue
        try:
            suffix = video.relative_to(dest)
        except ValueError:
            continue
        matched.append((len(dest.parts), src / suffix, src))
    if not matched:
        raise RuntimeError('No matching Docker bind mount; no host publication')
    matched.sort(key=lambda x: x[0], reverse=True)
    if len(matched)>1 and matched[0][0]==matched[1][0]:
        raise RuntimeError('Ambiguous Docker mounts for movie')
    _, path, root = matched[0]
    if not path.is_file() or path.is_symlink() or not root.is_dir():
        raise RuntimeError('Mapped host video missing or symlinked')
    canonical = path.resolve(strict=True)
    if not canonical.is_relative_to(root.resolve(strict=True)):
        raise RuntimeError('Mapped host video escapes expected Docker mount')
    return path


def existing_japanese(video):
    pattern=re.compile(r'\.(?:ja|jp|jpn|japanese)(?:\.[^.]+)?\.(?:srt|ass|ssa|vtt)$',re.I)
    return [path for path in video.parent.iterdir()
            if path.is_file() and path.name.casefold().startswith(video.stem.casefold()+'.')
            and pattern.search(path.name)]


def publish_from_copy(video, aligned, apply=False):
    target=video.with_name(video.stem+TARGET_SUFFIX)
    if existing_japanese(video) or target.exists() or target.is_symlink():
        raise RuntimeError('Japanese subtitle already present: refusing overwrite')
    if not os.access(video.parent,os.W_OK|os.X_OK):
        raise RuntimeError('Host movie directory not writable by current user; mount left unchanged')
    if not apply:
        print('HOST_PLAN_ONLY',target.name,'no media changed',flush=True)
        return None
    if not aligned.is_file() or aligned.is_symlink() or not 32 < aligned.stat().st_size < 3_000_000:
        raise RuntimeError('Staged aligned subtitle missing or unexpected size')
    fd, temp=tempfile.mkstemp(prefix='.bruiser-ja-',suffix='.tmp',dir=video.parent)
    try:
        with os.fdopen(fd,'wb') as out, aligned.open('rb') as source:
            shutil.copyfileobj(source,out)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp,0o644)
        if existing_japanese(video) or target.exists() or target.is_symlink():
            raise RuntimeError('Concurrent Japanese subtitle found; no publication')
        os.link(temp,target)  # No replacement. Atomic create-only final sidecar.
    finally:
        Path(temp).unlink(missing_ok=True)
    print('HOST_PUBLISHED_UNVERIFIED_JAPANESE',target.name,'bytes',target.stat().st_size,
          'original_video_unchanged',True,flush=True)
    return target


def run(args):
    video=Path(args.movie_container_path)
    report=Path(args.report)
    if (not video.is_absolute() or '..' in video.parts
        or not report.is_absolute() or '..' in report.parts
        or not re.fullmatch(r'report-[0-9a-f]{20}\.json',report.name)
        or report.parent.name != hashlib.sha256(str(video).encode()).hexdigest()[:20]):
        raise RuntimeError('Expected full exact movie path and matching cached report path')
    if not args.rescue_script.is_file():
        raise RuntimeError('Pinned rescue script not present')
    command=['exec','-i','-e','PYTHONPATH=/app',args.container,
             'python3','-','--title',args.title,'--from-staged',str(report)]
    verification=docker(command,input_bytes=args.rescue_script.read_bytes()).stdout.decode('utf-8','replace')
    print(verification.strip(),flush=True)
    if ('STAGED_CANDIDATE_APPROVED_MECHANICALLY' not in verification
        or 'PLAN_ONLY' not in verification
        or 'FILM_VIDEO_MATCHED '+video.name+' ' not in verification
        or 'HELD_' in verification):
        raise RuntimeError('In-container cached source did not pass read-only screening')
    mounts=json.loads(docker(['inspect','--format','{{json .Mounts}}',args.container]).stdout)
    host_video=host_path_for_movie(mounts,str(video))
    print('HOST_MOVIE_CONFIRMED',host_video.name,flush=True)
    # No need to download provider source or run ffsubsync a second time.
    if existing_japanese(host_video):
        raise RuntimeError('Japanese subtitle exists on host; no publication')
    with tempfile.TemporaryDirectory(prefix='bruiser-ja-publish-') as temporary:
        scratch=Path(temporary)/'aligned.srt'
        aligned=report.parent/('aligned-'+report.stem.removeprefix('report-')+'.srt')
        docker(['cp',args.container+':'+str(aligned),str(scratch)])
        return publish_from_copy(host_video,scratch,apply=args.apply)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--container',default='sublarr-pilot')
    p.add_argument('--movie-container-path',required=True)
    p.add_argument('--report',required=True)
    p.add_argument('--title',required=True)
    p.add_argument('--rescue-script',required=True,type=Path)
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try:
        run(a)
    except (RuntimeError,OSError,subprocess.CalledProcessError,ValueError) as exc:
        print('HOST_PUBLISH_HELD',type(exc).__name__,str(exc)[:210],file=sys.stderr)
        sys.exit(1)


if __name__=='__main__': main()
