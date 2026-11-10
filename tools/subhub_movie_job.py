#!/usr/bin/env python3
"""One movie, Japanese first: existing Sublarr discovery/sync + host publication.

Run on the OptiPlex as its owner. Exact video and release year required.
No Jellyfin catalog identity or stale movie picker is used.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

try:
    from . import subhub_publish_movie_candidate as publisher
except ImportError:
    import subhub_publish_movie_candidate as publisher

RESCUE=Path(__file__).with_name("bruiser_ja_movie_rescue.py")

def run_one(video, title, year, *, apply=False, runner=subprocess.run):
    video=publisher.video_safety(Path(video))
    if not RESCUE.is_file() or RESCUE.is_symlink():
        raise RuntimeError("movie_rescue_worker_not_installed")
    if not title or not 4<=len(title)<=160 or not 1880<=year<=2100:
        raise RuntimeError("invalid_movie_title_or_year")
    if publisher.existing_ja(video):
        return {"state":"covered","video":str(video),
                "message":"Japanese sidecar already present; no provider queried"}
    container_video=publisher.container_path(video,runner=runner)
    args=["docker","exec","-i","-e","PYTHONPATH=/app",
          "sublarr-pilot","python3","-",
          "--title",title,"--year",str(year),"--video-path",container_video,
          "--max-downloads","3","--stage-only","--apply"]
    if not apply:
        return {"state":"ready","video":str(video),
                "message":"Ready to find and synchronize Japanese subtitles"}
    run=runner(args,input=RESCUE.read_bytes(),stdout=subprocess.PIPE,
               stderr=subprocess.PIPE,timeout=1800,check=False)
    if run.returncode:
        # No raw provider credentials or subtitle dialogue sent to GUI.
        raise RuntimeError("movie_provider_or_sync_failed")
    marker="MOVIE_JA_HOST_PUBLISH_READY "
    lines=run.stdout.decode("utf-8","replace").splitlines()
    notices=[line[len(marker):] for line in lines if line.startswith(marker)]
    if not notices:
        if any("SOURCE_MISS" in line for line in lines):
            return {"state":"missing_ja","video":str(video),
                    "message":"No approved Japanese subtitle in this search. Review saved candidates or try other sources before considering translation; English is not required for Japanese sourcing."}
        if any("NO_APPROVED_CANDIDATE" in line for line in lines):
            return {"state":"held","video":str(video),
                    "message":"Japanese subtitles found but timing/content needs repair"}
        return {"state":"held","video":str(video),
                "message":"Japanese subtitle was not approved for publication"}
    if len(notices)!=1:
        raise RuntimeError("ambiguous_validated_movie_candidates")
    report=json.loads(notices[0])
    if report.get("video")!=container_video:
        raise RuntimeError("validated_video_identity_changed")
    return publisher.process(video,report["report"],apply=True)

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video",required=True,type=Path)
    ap.add_argument("--title",required=True)
    ap.add_argument("--year",required=True,type=int)
    ap.add_argument("--apply",action="store_true")
    args=ap.parse_args(argv)
    result=run_one(args.video,args.title,args.year,apply=args.apply)
    print("MOVIE_JA_RESULT",json.dumps(result,ensure_ascii=False),flush=True)

if __name__=="__main__":
    try:main()
    except (RuntimeError,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print("MOVIE_JA_HELD",str(exc)[:180],file=sys.stderr)
        raise SystemExit(1)
