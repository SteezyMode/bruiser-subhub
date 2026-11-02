#!/usr/bin/env python3
"""Install a low-rate daily *user* timer for Jellyfin EN-source inventory.

Never edits existing Jellyfin settings, native/system services, or crontabs.
Uses cached private Jellyfin token obtained by the first interactive pass.
If user systemd isn't available, report that scheduling is unavailable,
leaving the manual inventory/fill command fully functional.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

UNIT='bruiser-english-source'
SERVICE=f"""[Unit]
Description=Inventory Jellyfin English subtitles; acquire hash-perfect sources

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 %h/bruiser-pilot/english-source-code/library_english_sources.py run --budget 5
Nice=10
IOSchedulingClass=idle
TimeoutStartSec=90min
NoNewPrivileges=true
"""
TIMER=f"""[Unit]
Description=Daily low-rate Jellyfin English subtitle source acquisition

[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=30min
Persistent=true
Unit={UNIT}.service

[Install]
WantedBy=timers.target
"""


def write_unit(folder,name,content):
    path=Path(folder)/name
    if path.is_symlink():
        raise RuntimeError('Refusing symlinked systemd user unit')
    if path.exists():
        if not path.is_file() or path.read_text(encoding='utf8')!=content:
            raise RuntimeError('Existing user unit differs; refusing overwrite')
        return 'unchanged'
    flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY
    fd=os.open(path,flags,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as f:
            f.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return 'created'


def setup(home=None,runner=subprocess.run,log=print):
    home=Path(home or Path.home())
    user_dir=home/'.config/systemd/user'
    user_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    if user_dir.is_symlink():
        raise RuntimeError('Unsafe systemd user directory')
    one=write_unit(user_dir,UNIT+'.service',SERVICE)
    two=write_unit(user_dir,UNIT+'.timer',TIMER)
    results=[]
    for cmd in (
        ['systemctl','--user','daemon-reload'],
        ['systemctl','--user','enable','--now',UNIT+'.timer'],
        ['systemctl','--user','is-active',UNIT+'.timer'],
    ):
        result=runner(cmd,capture_output=True,text=True,timeout=20)
        results.append(result.returncode)
        if result.returncode:
            break
    if all(x==0 for x in results) and len(results)==3:
        log('EN_TIMER','active','03:30_local_daily',
            'search_budget_5','service_unit_'+one,'timer_unit_'+two)
        return True
    log('EN_TIMER','not_active','user_systemd_unavailable_or_error',
        'manual_run_still_available')
    return False


if __name__=='__main__':
    try:
        success=setup()
    except Exception as exc:
        print('EN_TIMER_BLOCKED',type(exc).__name__,file=sys.stderr)
        success=False
    raise SystemExit(0 if success else 1)
