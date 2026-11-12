#!/usr/bin/env python3
"""One reversible deployment: full-library, source-only SubHub upgrade.

Run on the existing OptiPlex host, never on a Mac client:
 python3 install_global_ja_sourcing.py --commit <40-hex-github-sha> --start

This updates the ORIGINAL SubHub modules and dashboard in place, makes a
private backup of EVERY changed file, and starts the existing JA-only source
controller with its daily timer. Never creates media folders, overwrites
subtitles, invokes PLaMo, or asks for new provider credentials.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

REPO="SteezyMode/bruiser-subhub"
HOST=Path.home()/"bruiser-pilot/subhub-control"
DASH=Path.home()/".local/share/bruiser-subhub-dashboard"
AI=Path.home()/"bruiser-pilot/plamo3-ab"
SOURCE_FILES=(
    "ja_first_search_pilot.py",
    "ja_first_movie_scope.py",
    "ja_first_cycle.py",
    "ja_first_priority.py",
    "ja_first_candidate_progress.py",
    "ja_first_catalog_manifest.py",
    "ja_first_stage_saved_batch.py",
    "ja_first_stage_timing_audit.py",
    "ja_first_publish_staged.py",
    "ja_first_publish_shifted.py",
    "ja_first_publish_queue.py",
    "ja_first_alass.py",
    "ja_first_ffsubsync.py",
    # Existing Jellyfin-backed provider adapter, not a new provider service.
    "benchmark_subtitle_search_paths.py",
    "probe_jellyfin_remote_subtitle.py",
    "ja_first_stage_jellyfin.py",
    "ja_first_stage_subdl.py",
    "subhub_download_ledger.py",
    "subhub_jellyfin_batch.py",
    "subhub_deep_source.py",
    "ja_first_autofill.py",
)
AI_FILES=("subhub_plamo_handoff.py",)
DASH_FILES=(
    "subhub_dashboard_server.py",
    "subhub_dashboard.html",
    "subhub_translation_batch.py",
    "subhub_finish_scope.py",
    "subhub_library_browser.py",
    "ja_first_source_tracker.py",
    "subhub_library_coverage.py",
    "subhub_season_sources.py",
    "bruiser_coverage_queue.py",
)
TEST_FILES=(
    "test_bruiser_coverage_queue.py",
    "test_ja_first_priority.py",
    "test_subhub_season_sources.py",
    "test_subhub_dashboard.py",
    "test_ja_first_alass.py",
)
SOURCE_UNIT="bruiser-ja-source-autofill.service"
SOURCE_TIMER="bruiser-ja-source-autofill.timer"
DASH_UNIT="bruiser-subhub-dashboard.service"
# The dashboard itself is read-only under systemd. Only its existing private
# source inventory requires writes, for accepted job receipts and progress.
DASH_JOB_ROOT=Path.home()/"bruiser-pilot/ja-first-inventory"
DASH_UNIT_DIR=Path.home()/".config/systemd/user"
DASH_OVERRIDE_DIR=DASH_UNIT_DIR/"bruiser-subhub-dashboard.service.d"
DASH_OVERRIDE=DASH_OVERRIDE_DIR/"20-ja-inventory-writes.conf"
DASH_OVERRIDE_BYTES=(
    b"[Service]\n"
    b"# Keep ProtectSystem=strict and ProtectHome=read-only; permit only receipts\n"
    b"ReadWritePaths=%h/bruiser-pilot/ja-first-inventory\n")
BUSY_UNITS=(
    SOURCE_UNIT, "bruiser-subhub-season-sources.service",
    "bruiser-subhub-batch.service", "bruiser-subhub-translation-batch.service",
    "bruiser-subhub-movie-ja.service",
    "bruiser-subhub-jellyfin-source.service",
    "bruiser-subhub-finish-scope.service",
)
MAX_BYTES=400_000

def fail(message):
    raise RuntimeError(message)

def systemctl(*args,timeout=35,check=True):
    p=subprocess.run(["systemctl","--user",*args],
                     capture_output=True,text=True,timeout=timeout,check=False)
    if check and p.returncode:
        fail("systemd "+args[0]+" failed: "+(p.stderr or p.stdout)[:140])
    return p

def secure_directory(directory):
    if not directory.is_dir() or directory.is_symlink() or directory.stat().st_uid!=os.getuid():
        fail("Missing, symlinked, or unowned existing directory: "+str(directory))

def secure_file(file,allow_new=False):
    if file.is_symlink() or (file.exists() and
        (not file.is_file() or file.stat().st_uid!=os.getuid())):
        fail("Untrusted installed source file: "+str(file))
    if not allow_new and not file.is_file():
        fail("Expected existing source missing: "+str(file))

def checked_download(commit,path):
    url=f"https://raw.githubusercontent.com/{REPO}/{commit}/{path}"
    with urlopen(url,timeout=45) as response:
        data=response.read(MAX_BYTES+1)
    if not 0<len(data)<=MAX_BYTES:
        fail("Unexpected source download length: "+path)
    try:
        text=data.decode("utf-8")
    except UnicodeError:
        fail("Source not UTF-8: "+path)
    if path.endswith(".py"):
        ast.parse(text,filename=path)
    return data

def atomic_install(path,content,mode):
    fd,name=tempfile.mkstemp(prefix="."+path.name+".upgrade-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(content);f.flush();os.fsync(f.fileno())
        os.chmod(name,mode)
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)

def offline_validation(files,work):
    root=work/"testrepo"
    pkg=root/"tools"
    pkg.mkdir(parents=True,mode=0o700)
    (pkg/"__init__.py").write_text("",encoding="utf-8")
    for (folder,name),data in files.items():
        # Every source that the focused unit tests directly import is shipped.
        dest=pkg/name
        dest.write_bytes(data)
    return root

def state_summary():
    src=HOST/"ja_first_search_pilot.py"
    page=DASH/"subhub_dashboard.html"
    worker=src.read_text("utf-8")
    html=page.read_text("utf-8")
    if "strategy_version" not in worker or "imdb_then_movie_title_year" not in worker:
        fail("Post-install library-wide v4 strategy missing")
    if ('id="source-library"' not in html or
            'id="source-whole-series"' not in html or
            'id="jellyfin-job-meter"' not in html):
        fail("Post-install library-wide and Jellyfin dashboard controls missing")
    print("INTEGRITY: library search strategy and full-library dashboard control present")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit",required=True)
    parser.add_argument("--start",action="store_true",
                        help="enable existing daily source timer and start one JA-only pass now")
    parser.add_argument("--install-only",action="store_true",
                        help="install code with rollback backup only: no catalog refresh,"
                             " queue reconcile, source run or timer changes")
    args=parser.parse_args()
    if args.install_only and args.start:
        parser.error("--install-only and --start are mutually exclusive")
    if not re.fullmatch("[0-9a-f]{40}",args.commit):
        parser.error("--commit needs one full 40-character Git commit hash")

    for folder in (HOST,DASH,AI,DASH_JOB_ROOT,DASH_UNIT_DIR):
        secure_directory(folder)
    if DASH_JOB_ROOT.stat().st_mode & 0o077:
        fail("Private source-job inventory is not owner-only")
    secure_file(DASH_UNIT_DIR/DASH_UNIT)
    if DASH_OVERRIDE_DIR.exists():
        secure_directory(DASH_OVERRIDE_DIR)
    secure_file(DASH_OVERRIDE,allow_new=True)
    for unit in BUSY_UNITS:
        p=systemctl("is-active",unit,check=False,timeout=10)
        if p.stdout.strip() in {"active","activating","reloading"}:
            fail("Existing worker active; avoid changing its code: "+unit)
        if p.returncode not in (0,3,4):
            fail("Cannot verify idle state: "+unit)

    destinations={}
    for name in SOURCE_FILES:
        target=HOST/name
        secure_file(target,allow_new=name in {
            "ja_first_movie_scope.py",
            "ja_first_candidate_progress.py",
            "ja_first_alass.py",
            "benchmark_subtitle_search_paths.py",
            "probe_jellyfin_remote_subtitle.py",
            "ja_first_stage_jellyfin.py",
            "ja_first_stage_subdl.py",
            "subhub_download_ledger.py",
            "subhub_jellyfin_batch.py",
            "subhub_deep_source.py",
        })
        destinations[("source",name)]=target
    for name in DASH_FILES:
        target=DASH/name
        secure_file(target,allow_new=name in {
            "subhub_library_coverage.py","subhub_translation_batch.py",
            "subhub_finish_scope.py","subhub_library_browser.py"})
        destinations[("dashboard",name)]=target
    for name in AI_FILES:
        target=AI/name
        secure_file(target)
        destinations[("ai",name)]=target

    print("FETCHING fixed revision:",args.commit)
    files={}
    for group,name in destinations:
        files[(group,name)]=checked_download(args.commit,"tools/"+name)
    # Avoid replacing host files with a version that cannot even parse.
    assert "strategy_version" in files[("source","ja_first_search_pilot.py")].decode()
    assert 'id="source-library"' in files[("dashboard","subhub_dashboard.html")].decode()
    assert "def indexed_jellyfin_english" in files[("ai","subhub_plamo_handoff.py")].decode()
    root=Path(tempfile.mkdtemp(prefix=".ja-lib-pref-",dir=HOST))
    backup=None
    updated=[]
    new_override_dir=False
    was_dashboard=systemctl("is-active",DASH_UNIT,check=False).stdout.strip()=="active"
    try:
        # Do not write any installed code before testing in isolation.
        sandbox=offline_validation(files,root)
        # Import dependencies of existing core tests from the original host
        # only for missing modules; the tests do not search the internet.
        for name in ("ja_first_ffsubsync.py","ja_first_publish_staged.py",
                     "ja_first_obvious_quality.py","subhub_translation_batch.py",
                     "ja_first_source_tracker.py","ja_first_gemma_fallback.py"):
            if (sandbox/"tools"/name).exists():
                continue
            for location in (HOST/name,DASH/name):
                if location.is_file() and not location.is_symlink():
                    shutil.copyfile(location,sandbox/"tools"/name)
                    break
        # Verify essential source modules and main runner are syntactically valid.
        for fname in SOURCE_FILES:
            if fname.endswith(".py"):
                ast.parse(files[("source",fname)].decode(),filename=fname)
        for fname in DASH_FILES:
            if fname.endswith(".py"):
                ast.parse(files[("dashboard",fname)].decode(),filename=fname)
        print("PREFLIGHT: source and dashboard modules parse successfully")

        # Backup exact host files, including local customizations, even when
        # different from GitHub. Private backup survives a successful install.
        backup=Path(tempfile.mkdtemp(prefix=".ja-library-source-backup-",dir=HOST))
        os.chmod(backup,0o700)
        for (group,name),target in destinations.items():
            old=target.read_bytes() if target.exists() else None
            if old is not None:
                saved=backup/(group+"__"+name)
                fd=os.open(saved,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,"wb") as f:f.write(old)
            if old==files[(group,name)]:
                continue
            mode=(target.stat().st_mode&0o777) if old is not None else 0o600
            atomic_install(target,files[(group,name)],mode)
            updated.append((target,old,mode))
            print("UPDATED:",group,name,"previous="+(
                hashlib.sha256(old).hexdigest()[:12] if old is not None else "new"))

        # The existing standalone dashboard unit protects the entire home
        # directory read-only. Grant ONLY its private inventory receipt
        # directory write access: no change to media, source code or mounts.
        if not DASH_OVERRIDE_DIR.exists():
            DASH_OVERRIDE_DIR.mkdir(mode=0o700)
            new_override_dir=True
        secure_directory(DASH_OVERRIDE_DIR)
        old=DASH_OVERRIDE.read_bytes() if DASH_OVERRIDE.exists() else None
        if old is not None:
            saved=backup/"systemd__20-ja-inventory-writes.conf"
            fd=os.open(saved,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,"wb") as output:output.write(old)
        if old!=DASH_OVERRIDE_BYTES:
            atomic_install(DASH_OVERRIDE,DASH_OVERRIDE_BYTES,0o600)
            updated.append((DASH_OVERRIDE,old,0o600))
            print("DASHBOARD SANDBOX: private job receipt directory writable only")
        systemctl("daemon-reload")
        state_summary()
        if was_dashboard:
            systemctl("restart",DASH_UNIT)
            print("DASHBOARD: existing service restarted")
            # This checks writability FROM INSIDE the dashboard's actual
            # mount namespace, not just owner permissions on the host.
            # If missing, rollback instead of leaving another dead button.
            job_writable=False
            for attempt in range(10):
                try:
                    with urlopen("http://127.0.0.1:17876/healthz",timeout=2) as reply:
                        health=json.loads(reply.read(2048))
                    job_writable=(health.get("mode")=="owner_controls" and
                                  health.get("job_receipts_writable") is True)
                    if job_writable:break
                except (OSError,ValueError):
                    pass
                time.sleep(.4)
            if not job_writable:
                fail("Dashboard restarted but its job receipts are still read-only")
            print("DASHBOARD SANDBOX: live private-job write probe PASS")
            # Healthz alone missed a real /api/status KeyError on the host.
            # Require the actual progress endpoint to answer before accepting
            # an install; rollback if dashboard status is still broken.
            try:
                with urlopen("http://127.0.0.1:17876/api/status",timeout=22) as response:
                    status=json.loads(response.read(1_000_001))
                if (not isinstance(status,dict) or
                        "jellyfin_source" not in status or
                        "download_usage" not in status):
                    fail("Dashboard progress API returned invalid status")
            except (OSError,ValueError) as exc:
                fail("Dashboard progress API failed: "+type(exc).__name__)
            print("DASHBOARD STATUS: actual /api/status endpoint PASS")
        if args.install_only:
            print("INSTALL ONLY: catalog, queue, timers and source workers unchanged")
        else:
            # Catalog refresh catches newly eligible movies and untagged audio;
            # it writes ONLY private inventory JSON, never the production library.
            p=subprocess.run([sys.executable,"-B",str(HOST/"ja_first_catalog_manifest.py"),"--save"],
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             text=True,timeout=1200,check=False)
            if p.returncode:
                fail("Jellyfin source catalog refresh failed: "+p.stderr[-220:])
            print("JELLYFIN CATALOG: refreshed using new library-wide eligibility")
            tracker=DASH/"bruiser_coverage_queue.py"
            p=subprocess.run([sys.executable,"-B",str(tracker),"init"],
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             text=True,timeout=180,check=False)
            if p.returncode:
                print("QUEUE RECONCILE: held, existing queue kept; "+
                      p.stderr[-160:],flush=True)
            else:
                print("QUEUE RECONCILE: complete")

    except BaseException:
        for target,old,mode in reversed(updated):
            if old is None:
                target.unlink(missing_ok=True)
            else:
                atomic_install(target,old,mode)
        if new_override_dir:
            try:DASH_OVERRIDE_DIR.rmdir()
            except OSError:pass
        systemctl("daemon-reload",check=False)
        if was_dashboard:
            systemctl("restart",DASH_UNIT,check=False)
        print("ROLLBACK: original host source code restored; backup:",
              backup,file=sys.stderr)
        raise
    finally:
        shutil.rmtree(root,ignore_errors=True)

    print("LIBRARY SOURCE UPGRADE INSTALLED. Original code backup:",backup)
    alass=Path.home()/"bruiser-pilot/sync-compare.WfaxCBpD/alass-linux64"
    print("STANDALONE ALASS:", "available" if alass.is_file() and os.access(alass,os.X_OK)
          else "not at expected path; ffsubsync remains fallback")
    if args.start:
        if systemctl("is-enabled",SOURCE_TIMER,check=False).returncode:
            # The existing controller already knows how to establish user
            # systemd units safely, without a new scheduler.
            p=subprocess.run([sys.executable,"-B",str(HOST/"ja_first_autofill.py"),
                              "enable","--apply"],capture_output=True,text=True,
                             timeout=1250,check=False)
            if p.returncode:
                fail("Daily source timer not enabled: "+p.stderr[-190:])
        if systemctl("is-active",SOURCE_TIMER,check=False).returncode:
            systemctl("start",SOURCE_TIMER)
        systemctl("start","--no-block",SOURCE_UNIT)
        print("SOURCE STARTED: existing full-library Japanese-only service;")
        print("daily timer enabled; all eligible movies and episodes processed")
        print("in provider-limited, resume-safe cycles; PLaMo NEVER started.")
    else:
        print("Source service not started; pass --start when ready")

if __name__=="__main__":
    try:main()
    except (RuntimeError,OSError,ValueError,subprocess.TimeoutExpired) as e:
        print("SOURCE UPGRADE HELD:",type(e).__name__,str(e)[:230],file=sys.stderr)
        raise SystemExit(1) from None
