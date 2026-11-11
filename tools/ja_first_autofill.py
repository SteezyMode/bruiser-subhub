#!/usr/bin/env python3
"""One source-only Japanese subtitle filler for the existing Jellyfin library.

Runs the proven host search -> staged provider acquisition -> junk QA -> ffsubsync
-> atomic create-only publication pipeline. No DIY translation or new accounts.
A separate daily user timer is optional. Prevent duplicate provider scans by
moving Sublarr's *periodic wanted provider search* to this host controller,
while leaving Sublarr's library scan and UI intact.

Host OptiPlex only; Python standard library. Never touch original video bytes.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"
NEXT_BUDGET_FILE = ROOT / ".source-next-run-budget.json"
SCOPE_FILE = ROOT / ".source-scope.json"
MOVIE_SCOPE = "horror-drama-folders"
DEFAULT_SEARCH_BUDGET = 600
CODE = Path.home() / "bruiser-pilot/subhub-control"
UNIT = "bruiser-ja-source-autofill"
NAME = UNIT + ".timer"
SVC = UNIT + ".service"
USER_UNITS = Path.home() / ".config/systemd/user"
PINNED = (
    "ja_first_cycle.py", "ja_first_catalog_manifest.py",
    "ja_first_publish_queue.py", "ja_first_alass.py", "ja_first_ffsubsync.py",
    "ja_first_obvious_quality.py",
)
CONFIG_KEYS = (
    "wanted_search_interval_hours", "wanted_search_on_startup",
    "wanted_auto_translate", "translation_enabled",
    "webhook_auto_translate", "jellyfin_play_translate_enabled",
    "subtitle_automation_enabled", "upgrade_enabled",
    "provider_budget_enabled", "target_language",
)

SERVICE = """[Unit]
Description=Source and synchronize Japanese subtitles for Jellyfin (no AI)

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 %h/bruiser-pilot/subhub-control/ja_first_autofill.py once --apply
Nice=10
IOSchedulingClass=idle
UMask=0077
NoNewPrivileges=true
TimeoutStartSec=8h
"""
LEGACY_SERVICE = SERVICE.replace("TimeoutStartSec=8h", "TimeoutStartSec=90min")
TIMER = """[Unit]
Description=Daily Japanese sourced-subtitle acquisition and synchronization

[Timer]
OnCalendar=*-*-* 09:15:00
RandomizedDelaySec=20min
Persistent=false
Unit=bruiser-ja-source-autofill.service

[Install]
WantedBy=timers.target
"""
# Previous timer ran BEFORE OpenSubtitles' 09:00 JST quota reset.
LEGACY_TIMER = TIMER.replace('09:15:00', '05:15:00')

# Execute inside the already installed Sublarr image, reusing existing local
# API auth. The only allowed API write is PUT config of the two wanted-search
# scheduler fields, not provider credentials, folders, translation or upgrades.
API_WORKER = r'''
import json,sys
from urllib.request import Request,urlopen
from config import get_settings
task=json.load(sys.stdin)
endpoint=task["endpoint"]
if endpoint not in ("/api/v1/config","/api/v1/wanted/scanner/status"):
    raise SystemExit("disallowed_api_endpoint")
data=task.get("payload")
method="PUT" if data is not None else "GET"
if data is not None and (endpoint!="/api/v1/config" or
        set(data)-{"wanted_search_interval_hours","wanted_search_on_startup"}):
    raise SystemExit("disallowed_config_mutation")
headers={}
key=get_settings().api_key
if key: headers["X-Api-Key"]=key
if data is not None: headers["Content-Type"]="application/json"
req=Request("http://127.0.0.1:5765"+endpoint,
            headers=headers,method=method,
            data=None if data is None else json.dumps(data).encode("utf8"))
with urlopen(req,timeout=20) as response:
    obj=json.load(response)
print("BRUISER_SUBLARR_RESULT_JSON:"+json.dumps(obj))
'''


def run(args, *, timeout=90, input_text=None, runner=subprocess.run):
    result=runner(args, input=input_text, text=True, capture_output=True,
                  timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError("command_failed:"+str(Path(args[0]).name if "/" in args[0] else args[0])+
                           ":"+str(result.returncode))
    return result.stdout


def api(endpoint, payload=None, *, runner=run):
    args=["docker","exec","-i","-e","PYTHONPATH=/app","sublarr-pilot",
          "python3","-c",API_WORKER]
    out=runner(args,input_text=json.dumps({"endpoint":endpoint,"payload":payload}),
               timeout=40)
    for line in reversed(out.splitlines()):
        if line.startswith("BRUISER_SUBLARR_RESULT_JSON:"):
            result=json.loads(line.partition(":")[2])
            if not isinstance(result,dict):
                raise RuntimeError("sublarr_unexpected_api_response")
            return result
    raise RuntimeError("sublarr_api_result_missing")


def config(*, request=api):
    value=request("/api/v1/config")
    if not all(k in value for k in CONFIG_KEYS):
        raise RuntimeError("sublarr_config_schema_missing_safety_keys")
    return value


def safe_source_settings(value):
    if str(value.get("target_language","")).casefold() not in {"ja","jpn","japanese"}:
        raise RuntimeError("sublarr_target_not_japanese")
    for name in (
        "wanted_auto_translate", "translation_enabled",
        "webhook_auto_translate", "jellyfin_play_translate_enabled",
        "subtitle_automation_enabled", "upgrade_enabled",
    ):
        if value.get(name) is not False:
            raise RuntimeError("unexpected_automatic_ai_or_upgrade_setting:"+name)
    if value.get("provider_budget_enabled") is not True:
        raise RuntimeError("provider_budget_not_enabled")


def native_search_disabled(value):
    return value.get("wanted_search_interval_hours")==0 and \
        value.get("wanted_search_on_startup") is False


def lock():
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    if ROOT.is_symlink() or ROOT.stat().st_mode&0o077:
        raise RuntimeError("inventory_folder_not_private")
    path=ROOT/".autofill.lock"
    fd=os.open(path,os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
    if os.fstat(fd).st_mode&0o077:
        os.close(fd)
        raise RuntimeError("insecure_autofill_lock")
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError("another_source_cycle_is_running") from None
    return fd


def ensure_installed():
    missing=[name for name in PINNED if not (CODE/name).is_file()
             or (CODE/name).is_symlink()]
    if missing:
        raise RuntimeError("controller_components_missing:"+",".join(missing))


def current_manifest_age():
    matches=sorted(ROOT.glob("ja-intake-*.json"))
    if not matches:
        return None
    path=matches[-1]
    if not path.is_file() or path.is_symlink() or path.stat().st_mode&0o077:
        raise RuntimeError("unsafe_inventory_manifest")
    return max(0,int(time.time()-path.stat().st_mtime))


def refresh_manifest(*, action=run):
    age=current_manifest_age()
    # Search/stage code refuses a manifest >72h old. Keep it <=20h old.
    if age is not None and age < 20*3600:
        print("CATALOG_REUSED age_hours",round(age/3600,1),flush=True)
        return
    print("REFRESHING_JELLYFIN_CATALOG",flush=True)
    action([sys.executable,str(CODE/"ja_first_catalog_manifest.py"),"--save"],
           timeout=1200)
    print("CATALOG_REFRESHED",flush=True)


def check_scheduler_idle(*, request=api):
    state=request("/api/v1/wanted/scanner/status")
    if state.get("is_searching"):
        raise RuntimeError("native_sublarr_search_currently_active")


def selected_source_scope():
    """The persistent owner choice, applied to ALL three source-only stages."""
    if not SCOPE_FILE.exists() and not SCOPE_FILE.is_symlink():
        return "all"
    if SCOPE_FILE.is_symlink():
        raise RuntimeError("source_scope_is_symlink")
    info=SCOPE_FILE.stat(follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
            or info.st_mode & 0o077 or info.st_size>500):
        raise RuntimeError("source_scope_file_not_private")
    doc=json.loads(SCOPE_FILE.read_text("utf-8"))
    if not isinstance(doc,dict) or set(doc)!={"scope"} or doc["scope"] not in ("all",MOVIE_SCOPE):
        raise RuntimeError("source_scope_invalid")
    return doc["scope"]


def configure_source_scope(scope):
    """Owner-only persistent scope change, with no provider or model calls."""
    if scope not in ("all",MOVIE_SCOPE):
        raise RuntimeError("unsupported_source_scope")
    fd=lock()
    try:
        previous=selected_source_scope()
        data=(json.dumps({"scope":scope},sort_keys=True)+"\n").encode()
        tmp_fd,tmp=tempfile.mkstemp(prefix=".source-scope-",dir=ROOT)
        try:
            with os.fdopen(tmp_fd,"wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(tmp,0o600)
            os.replace(tmp,SCOPE_FILE)
        finally:
            Path(tmp).unlink(missing_ok=True)
        print("SOURCE_SCOPE",previous,"->",scope,
              "persistent_for_all_future_source_only_cycles",flush=True)
    finally:
        os.close(fd)


def next_run_budget():
    """Read an explicitly configured, private one-time search budget."""
    if not NEXT_BUDGET_FILE.exists() and not NEXT_BUDGET_FILE.is_symlink():
        return DEFAULT_SEARCH_BUDGET, False
    if NEXT_BUDGET_FILE.is_symlink():
        raise RuntimeError("one_time_budget_is_symlink")
    info = NEXT_BUDGET_FILE.stat(follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise RuntimeError("one_time_budget_not_private_owned_file")
    content = NEXT_BUDGET_FILE.read_bytes()
    if len(content) > 1024:
        raise RuntimeError("one_time_budget_invalid_size")
    value = json.loads(content)
    if not isinstance(value, dict) or set(value) != {"search_budget"}:
        raise RuntimeError("one_time_budget_invalid_schema")
    budget = value["search_budget"]
    if type(budget) is not int or not 1 <= budget <= 600:
        raise RuntimeError("one_time_search_budget_outside_1_to_600")
    return budget, True


def set_next_run_budget(budget):
    """Prepare only the next scheduled or manually started source run.

    No service, provider or subtitle operations here. A successful source run
    consumes the override; interrupted runs retain it for a safe retry.
    """
    if type(budget) is not int or not 1 <= budget <= 600:
        raise RuntimeError("one_time_search_budget_outside_1_to_600")
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
        raise RuntimeError("inventory_folder_not_private")
    # Do not overwrite an unrelated file or bypass a symlink.
    if NEXT_BUDGET_FILE.exists() or NEXT_BUDGET_FILE.is_symlink():
        next_run_budget()
    data = (json.dumps({"search_budget":budget}, sort_keys=True) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=".next-budget-", dir=ROOT)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, NEXT_BUDGET_FILE)
    finally:
        Path(tmp).unlink(missing_ok=True)
    print("NEXT_SOURCE_CYCLE_BUDGET", budget, "one_time_only", flush=True)


def once(*, request=api, action=run):
    ensure_installed()
    fd=lock()
    try:
        settings=config(request=request)
        safe_source_settings(settings)
        if not native_search_disabled(settings):
            raise RuntimeError("native_wanted_search_still_enabled_no_duplicate_provider_queries")
        check_scheduler_idle(request=request)
        refresh_manifest(action=action)
        search_budget, custom_budget = next_run_budget()
        scope=selected_source_scope()
        print(f"RUNNING_SOURCES_ONLY_CYCLE search_budget={search_budget} "
              "stage_budget=200 publish_limit=200 "
              "(provider allowance still enforced)", flush=True)
        print("SOURCE SCOPE:", scope, flush=True)
        # Let output appear in systemd journal or manual terminal; don't
        # require a persistent shell or start any local translation model.
        result=subprocess.run(
            [sys.executable,"-u",str(CODE/"ja_first_cycle.py"),"cycle",
             "--sources-only","--apply","--search-budget",str(search_budget),
             "--stage-budget","200","--publish-limit","200",
             "--scope",scope],
            stdin=subprocess.DEVNULL, timeout=8*3600, check=False)
        if result.returncode:
            raise RuntimeError("sources_only_cycle_failed:"+str(result.returncode))
        if custom_budget:
            NEXT_BUDGET_FILE.unlink()
            print("ONE_TIME_SEARCH_BUDGET_CONSUMED next_cycle_default=600",
                  flush=True)
        print("AUTOFILL_CYCLE_COMPLETE",flush=True)
    finally:
        os.close(fd)


def secure_user_unit_directory():
    """Safely normalize only this user's systemd unit directory.

    A pre-existing group-writable user directory is common on older systems.
    Never chmod a foreign-owned path or a symlink. Narrow the permissions to
    0700 rather than rejecting forever or bypassing the security check.
    """
    if USER_UNITS.is_symlink():
        raise RuntimeError("user_systemd_directory_is_symlink")
    USER_UNITS.mkdir(parents=True,exist_ok=True,mode=0o700)
    if USER_UNITS.is_symlink():
        raise RuntimeError("user_systemd_directory_is_symlink")
    info=USER_UNITS.stat(follow_symlinks=False)
    if not USER_UNITS.is_dir() or info.st_uid != os.getuid():
        raise RuntimeError("user_systemd_directory_not_owned_by_current_user")
    if info.st_mode&0o077:
        USER_UNITS.chmod(0o700)
        fresh=USER_UNITS.stat(follow_symlinks=False)
        if fresh.st_uid != os.getuid() or fresh.st_mode&0o077:
            raise RuntimeError("user_systemd_directory_permissions_not_private")
        print("USER_SYSTEMD_PERMISSIONS_HARDENED 0700",flush=True)


def unit_file(name,content):
    secure_user_unit_directory()
    path=USER_UNITS/name
    if path.is_symlink():
        raise RuntimeError("existing_unit_is_symlink")
    if path.exists():
        if not path.is_file() or path.stat().st_uid!=os.getuid():
            raise RuntimeError("existing_user_unit_not_owned_regular_file")
        current=path.read_text("utf8")
        if current==content:
            return
        # Migrate ONLY known Bruiser service/time configurations.
        # Unknown/custom user systemd units are never overwritten.
        is_old_service = name==SVC and current==LEGACY_SERVICE
        is_old_timer = name==NAME and current==LEGACY_TIMER
        if not (is_old_service or is_old_timer):
            raise RuntimeError("different_existing_user_unit_refusing_overwrite")
        import tempfile
        fd,tmp=tempfile.mkstemp(prefix=".ja-source-unit-",dir=USER_UNITS)
        try:
            with os.fdopen(fd,"w",encoding="utf8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(tmp,0o600)
            os.replace(tmp,path)
            print("SOURCE_UNIT_UPDATED",name,flush=True)
        finally:
            Path(tmp).unlink(missing_ok=True)
        return
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"w",encoding="utf8") as out:
        out.write(content)


def enable(*,request=api,action=run):
    ensure_installed()
    if not (CODE/"ja_first_autofill.py").is_file():
        raise RuntimeError("autofill_controller_not_installed")
    settings=config(request=request)
    safe_source_settings(settings)
    check_scheduler_idle(request=request)
    # Establish that the existing Jellyfin catalog can be refreshed BEFORE
    # disabling Sublarr's native provider-search schedule.
    refresh_manifest()
    previous={k:settings[k] for k in
              ("wanted_search_interval_hours","wanted_search_on_startup")}
    if type(previous["wanted_search_interval_hours"]) is not int or not \
            0<=previous["wanted_search_interval_hours"]<=168 or \
            type(previous["wanted_search_on_startup"]) is not bool:
        raise RuntimeError("unexpected_original_search_scheduler_settings")

    # Create-only unit files + validate user systemd BEFORE modifying Sublarr.
    unit_file(SVC,SERVICE)
    unit_file(NAME,TIMER)
    action(["systemctl","--user","daemon-reload"],timeout=20)

    did_change=not native_search_disabled(settings)
    if did_change:
        response=request("/api/v1/config",{
            "wanted_search_interval_hours":0,"wanted_search_on_startup":False})
        if response.get("status")!="saved":
            raise RuntimeError("native_search_disable_response_not_saved")
    try:
        updated=config(request=request)
        safe_source_settings(updated)
        if not native_search_disabled(updated):
            raise RuntimeError("native_search_disable_not_verified")
        action(["systemctl","--user","enable","--now",NAME],timeout=25)
        action(["systemctl","--user","is-active","--quiet",NAME],timeout=20)
        print("JA_SOURCE_AUTOFILL_TIMER_ENABLED daily_09:15_local_plus_0_to_20min",
              "sublarr_native_provider_search_disabled",
              "sublarr_library_scanning_unchanged",
              "no_automatic_translation",flush=True)
    except Exception:
        try:
            action(["systemctl","--user","disable","--now",NAME],timeout=25)
        except Exception:
            pass
        if did_change:
            try:
                request("/api/v1/config",previous)
            except Exception:
                print("WARNING_NATIVE_SEARCH_RESTORE_FAILED",file=sys.stderr)
        raise


def status(*,request=api,action=run):
    ensure_installed()
    settings=config(request=request)
    age=current_manifest_age()
    print("SOURCE_AUTOFILL_STATUS",json.dumps({
        "native_wanted_search_interval_hours":settings["wanted_search_interval_hours"],
        "native_wanted_search_on_startup":settings["wanted_search_on_startup"],
        "host_timer":NAME,
        "manifest_age_hours":None if age is None else round(age/3600,1),
        "automation_safety":"source_only_no_ai",
        "source_scope":selected_source_scope(),
    },sort_keys=True),flush=True)
    try:
        out=action(["systemctl","--user","is-active",NAME],timeout=20).strip()
        print("SOURCE_TIMER_ACTIVE",out or "active",flush=True)
    except RuntimeError:
        print("SOURCE_TIMER_INACTIVE_OR_USER_SYSTEMD_UNAVAILABLE",flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("status","enable","once","next-budget","scope"),nargs="?",
                        default="status")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--search-budget",type=int,default=None)
    parser.add_argument("--scope",choices=("all",MOVIE_SCOPE),default=None)
    args=parser.parse_args(argv)
    if args.mode=="status":
        return status()
    if not args.apply:
        parser.error("enable, once and next-budget require --apply")
    if args.mode=="scope":
        if args.scope is None or args.search_budget is not None:
            parser.error("scope requires --scope all|horror-drama-folders")
        return configure_source_scope(args.scope)
    if args.scope is not None:
        parser.error("--scope is only valid with scope mode")
    if args.mode=="next-budget":
        if args.search_budget is None:
            parser.error("next-budget requires --search-budget 1..600")
        return set_next_run_budget(args.search_budget)
    if args.search_budget is not None:
        parser.error("--search-budget is only valid with next-budget")
    if args.mode=="enable":
        return enable()
    if args.mode=="once":
        return once()


if __name__=="__main__":
    try:
        main()
    except (RuntimeError,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        # Don't dump API secrets, provider credentials or subtitle dialogue.
        print("JA_SOURCE_AUTOFILL_HELD",type(exc).__name__,str(exc)[:175],
              file=sys.stderr)
        raise SystemExit(1) from None
