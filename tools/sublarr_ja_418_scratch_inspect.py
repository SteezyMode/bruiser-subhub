#!/usr/bin/env python3
"""Inspect one real OpenSubtitles Japanese result WITHOUT creating a media sidecar.

Runs in the running Sublarr container: PYTHONPATH=/app python3 -.
Wanted #418 is the established real American Dad S22E02 search hit.
- Queries interactive provider candidates for that same Wanted ID.
- Downloads ONE native OpenSubtitles result into a private /tmp scratch directory.
- Parses and checks real Japanese dialogue, coverage, metadata and timing.
- Uses Sublarr's own non-destructive ffsubsync sync_compare() against video.
- Saves candidate + private JSON report to /tmp/bruiser-ja-418-review.tar.gz
  for owner review (retrieve using docker cp); no media/DB publisher calls.

Side effects: one provider search, updates that wanted item's last_search_at;
ONE OpenSubtitles download consumes a provider download quota.
No AI translation, new workers, model changes, library scan, file publication,
auto-sync applying, config changes, or stored OpenSubtitles credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

ITEM_ID = 418
BASE = "http://127.0.0.1:5765"
ARCHIVE = Path("/tmp/bruiser-ja-418-review.tar.gz")
MAX_BYTES = 3_000_000
LANGS = {"ja", "jpn", "japanese"}
FILENAME = "American.Dad.S22E02.720p.x264-FENiX.mkv"
ASS_HEADER = b"[Script Info]"
JA_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def json_get(path, headers):
    req = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def select_candidate(results):
    """No name-only selection: target language, source provider, full dialogue."""
    out = []
    for r in results:
        if not isinstance(r, dict):
            continue
        if r.get("provider_name") != "opensubtitles":
            continue
        if str(r.get("language") or "").lower() not in LANGS:
            continue
        if r.get("forced") or str(r.get("kind") or "").lower() in ("forced", "signs"):
            continue
        sid = r.get("subtitle_id")
        if not isinstance(sid, str) or not sid or len(sid) > 128:
            continue
        score = r.get("score")
        if isinstance(score, bool) or not isinstance(score, (int,float)) or score < 170:
            continue
        out.append(r)
    # Identical release string beats arbitrary best score; neither proves JA quality.
    def rank(r):
        release = f'{r.get("filename") or ""} {r.get("release_info") or ""}'.casefold()
        return ("fenix" in release, float(r["score"]))
    return sorted(out, key=rank, reverse=True)[0] if out else None


def preview_values(items):
    return [
        {key: item[key] for key in
         ("provider_name","language","format","filename","release_info","score",
          "forced","kind","machine_translated","mt_confidence","uploader_name")
         if key in item and isinstance(item[key], (str,int,float,bool))}
        for item in items
    ]


def subtitle_kind(raw, default=""):
    """Detect actual subtitle representation, not the provider's predicted format."""
    first = raw[:4096].lstrip(b"\xef\xbb\xbf\r\n\t ")
    if ASS_HEADER in first[:256] and b"[Events]" in raw[:20000]:
        return ".ass"
    if first.startswith(b"WEBVTT"):
        return ".vtt"
    if re.search(rb"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->", first):
        return ".srt"
    # A very long ASS Script Info header can push Events beyond the first 20 KB.
    if first.startswith(ASS_HEADER):
        return ".ass"
    return {"ass":".ass","ssa":".ssa","srt":".srt","vtt":".vtt"}.get(
        str(default).lower(), "")


def video_duration(path):
    try:
        p = subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration",
             "-of","default=noprint_wrappers=1:nokey=1",str(path)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=20,
            check=True)
        return round(float(p.stdout.strip()),2)
    except Exception:
        return None


def summarize_cues(cues, duration_sec):
    texts=[str(c["text"]) for c in cues if str(c.get("text") or "").strip()]
    jap=[x for x in texts if JA_PATTERN.search(x)]
    count=len(cues)
    starts=[int(x["start"]) for x in cues]
    ends=[int(x["end"]) for x in cues]
    duration = duration_sec*1000 if duration_sec else None
    out={
        "dialogue_event_count":count,
        "nonblank_event_count":len(texts),
        "japanese_script_event_count":len(jap),
        "japanese_script_event_fraction":round(len(jap)/len(texts),3) if texts else None,
        "first_event_seconds":round(min(starts)/1000,2) if starts else None,
        "last_event_end_seconds":round(max(ends)/1000,2) if ends else None,
        "unreasonably_long_events":sum(int(x["end"])-int(x["start"])>30_000 for x in cues),
        "nonpositive_duration_events":sum(int(x["end"])<=int(x["start"]) for x in cues),
        "out_of_video_events":sum(int(x["end"])>duration+10_000 for x in cues) if duration else None,
        "dense_over_20_chars_per_s":sum(
            len(re.sub(r"\s+","",str(c["text"]))) / max((int(c["end"])-int(c["start"]))/1000,0.01)>20
            for c in cues),
    }
    # Select start/quarter/mid/3-quarter/end event times WITHOUT echoing copyrighted dialogue.
    selected=sorted(set(min(max(int(i*(count-1)/4),0),count-1) for i in range(5))) if count else []
    out["timeline_sample_seconds"]=[
        round(cues[i]["start"]/1000,1) for i in selected
    ]
    return out


def run():
    if ARCHIVE.exists() or ARCHIVE.is_symlink():
        raise RuntimeError("Private archive already exists; refusing overwrite")
    from config import get_settings
    settings=get_settings()
    headers={"X-Api-Key":settings.api_key} if settings.api_key else {}
    health=json_get("/api/v1/providers/health",headers)
    provider_status=next(
        (p for p in health.get("providers",[]) if p.get("name")=="opensubtitles"),{})
    if provider_status.get("gate")!="ok" or not provider_status.get("initialized"):
        raise RuntimeError("Native OpenSubtitles provider is not ready")
    cfg=json_get("/api/v1/config",headers)
    if cfg.get("wanted_auto_translate") is not False or cfg.get("upgrade_enabled") is not False:
        raise RuntimeError("Expected auto-translate and subtitle upgrade disabled")
    from db.wanted import get_wanted_item
    # We do not initialize a separate Flask database; verify identity through the
    # same HTTP endpoint used by Sublarr's UI.
    item=json_get("/api/v1/wanted?status=wanted&search=American.Dad.S22E02&per_page=20",headers)
    matches=item.get("data",[]) if isinstance(item,dict) else []
    exact=[x for x in matches if x.get("id")==ITEM_ID]
    if len(exact)!=1:
        raise RuntimeError("Wanted #418 no longer pending or not found in listing")
    wanted=exact[0]
    v=Path(str(wanted.get("file_path") or ""))
    if wanted.get("target_language") not in LANGS or wanted.get("subtitle_type")!="full":
        raise RuntimeError("Wrong Wanted language or subtitle type")
    if v.name!=FILENAME or not str(v).startswith("/media/") or v.is_symlink() or not v.is_file():
        raise RuntimeError("Wanted file/path changed since owner dry-run")
    print("VIDEO_MATCHED",v.name,"Wanted",ITEM_ID,flush=True)
    print("SEARCHING candidates; only this Wanted item, provider quota applies",flush=True)
    result=json_get(f"/api/v1/wanted/{ITEM_ID}/search-providers",headers)
    if result.get("error"):
        raise RuntimeError("Provider search held: "+str(result["error"])[:160])
    rows=result.get("results",[])
    if not isinstance(rows,list):
        raise RuntimeError("Candidate API schema mismatch")
    all_ja=[x for x in rows if x.get("provider_name")=="opensubtitles" and
            str(x.get("language","")).lower() in LANGS]
    candidate=select_candidate(rows)
    print("CANDIDATES_TOTAL",len(rows),"OPEN_SUBTITLES_JA",len(all_ja),flush=True)
    if candidate is None:
        print("NO_VERIFIED_JAPANESE_CANDIDATE no download made",flush=True)
        return
    print("SELECTED_CANDIDATE",json.dumps(preview_values([candidate])[0],ensure_ascii=False),flush=True)
    # We deliberately do NOT call the route /download-specific, which publishes
    # beside the video. Download one result directly into PRIVATE temporary storage.
    from providers.opensubtitles import OpenSubtitlesProvider
    provider=OpenSubtitlesProvider(
        api_key=getattr(settings,"opensubtitles_api_key",""),
        username=getattr(settings,"opensubtitles_username",""),
        password=getattr(settings,"opensubtitles_password",""),
    )
    try:
        provider.initialize()
        handle=provider.result_for_download(candidate["subtitle_id"],"ja")
        print("SCRATCH_DOWNLOAD starting one quota-counted native OpenSubtitles request",flush=True)
        content=provider.download(handle)
    finally:
        provider.terminate()
    if not isinstance(content,bytes) or not (32<len(content)<=MAX_BYTES):
        raise RuntimeError("Downloaded candidate empty, non-bytes or unexpectedly large")
    ext=subtitle_kind(content,handle.format.value)
    if ext not in (".ass",".ssa",".srt",".vtt"):
        raise RuntimeError("Downloaded subtitle file type unsupported")
    with tempfile.TemporaryDirectory(prefix="bruiser-ja-418-",dir="/tmp") as private:
        p=Path(private)
        source=p/("candidate"+ext)
        source.write_bytes(content)
        os.chmod(source,0o600)
        from services.sync_preview import load_cues, sync_compare
        cues=load_cues(str(source))
        if not cues:
            raise RuntimeError("Provider result contained no parseable cues")
        length=video_duration(v)
        checks=summarize_cues(cues,length)
        report={
            "schema":"bruiser-ja-scratch-inspect-v1",
            "wanted_id":ITEM_ID,"title":"American Dad S22E02",
            "video_file":v.name,"video_duration_seconds":length,
            "selected_provider_result":preview_values([candidate])[0],
            "download_bytes":len(content),
            "download_sha256":hashlib.sha256(content).hexdigest(),
            "detected_subtitle_format":ext,
            "content_mechanical_screen":checks,
            "screening_note":"Ja script, coverage and score are mechanical evidence, not human translation quality",
            "subtitle_published":False,"media_modified":False,
        }
        print("DOWNLOADED",len(content),"bytes",ext,"parsed_cues",len(cues),
              "japanese_cues",checks["japanese_script_event_count"],
              "video_seconds",length,flush=True)
        print("SYNC_PREVIEW starting non-destructive ffsubsync against real video",flush=True)
        try:
            comparison=sync_compare(str(source),video_path=str(v))
            engines=comparison.get("candidates",[])
            for result_item in engines:
                slim={k:result_item.get(k) for k in
                      ("engine","status","shift_ms","error") if k in result_item}
                if "error" in slim:
                    slim["error"]=str(slim["error"])[:180]
                report.setdefault("sync_candidates",[]).append(slim)
                print("SYNC_RESULT",json.dumps(slim,ensure_ascii=False),flush=True)
            if engines and engines[0].get("status")=="ok":
                shifted=engines[0].get("cues") or []
                report["sync_candidate_event_count"]=len(shifted)
                # Include no synced SRT candidate in archive until separately
                # confirmed to avoid passing it off as a validated replacement.
        except Exception as exc:
            report["sync_error"]=type(exc).__name__+": "+str(exc)[:180]
            print("SYNC_PREVIEW_HELD",report["sync_error"],flush=True)

        metadata=p/"report.json"
        metadata.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        os.chmod(metadata,0o600)
        # Strict create-only private archive: owner can docker cp then share for
        # actual Japanese-language quality assessment; no source media archived.
        fd=os.open(ARCHIVE,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,"wb") as fileobj:
                with tarfile.open(fileobj=fileobj,mode="w:gz") as tf:
                    tf.add(source,arcname=source.name,recursive=False)
                    tf.add(metadata,arcname=metadata.name,recursive=False)
        except BaseException:
            ARCHIVE.unlink(missing_ok=True)
            raise
    print("PRIVATE_REVIEW_ARCHIVE",str(ARCHIVE),flush=True)
    print("DONE: source video, JA sidecars, Wanted publication, model settings unchanged",flush=True)


if __name__=="__main__":
    try:
        run()
    except urllib.error.HTTPError as exc:
        print("CANDIDATE_INSPECT_HELD HTTP",exc.code,file=sys.stderr,flush=True)
        raise SystemExit(1) from None
    except (OSError,ValueError,RuntimeError) as exc:
        print("CANDIDATE_INSPECT_HELD",type(exc).__name__,str(exc)[:220],
              file=sys.stderr,flush=True)
        raise SystemExit(1) from None
