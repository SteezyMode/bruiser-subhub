#!/usr/bin/env python3
"""Idempotent user-level timer for one-source/day American Dad upkeep.

Only exact named private Bruiser user units; refuse modifications to an existing
different unit. Never uses sudo or changes native Jellyfin, Caddy, or SubHub.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

UNIT='bruiser-american-dad-maintenance'
LEGACY_SERVICE=f"""[Unit]
Description=Bruiser American Dad English source + selected-season subtitle maintenance
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 %h/bruiser-pilot/american-dad-auto-code/american_dad_maintenance.py
Nice=15
CPUWeight=10
CPUQuota=250%
MemoryMax=5G
IOSchedulingClass=idle
NoNewPrivileges=true
TimeoutStartSec=120min
"""
# The ORIGINAL unit was deployed on the host on 2026-11-02.
# Upgrade only that known exact unit; never clobber custom user units.
SERVICE=(LEGACY_SERVICE
    .replace('Type=oneshot','Type=exec')
    .replace('ExecStart=/usr/bin/python3 %h/',
             'ExecStart=/usr/bin/python3 -u %h/')
    .replace('TimeoutStartSec=120min',
             'RuntimeMaxSec=11h')
    .replace('NoNewPrivileges=true',
             'NoNewPrivileges=true\nKillMode=control-group'))
TIMER=f"""[Unit]
Description=Local English ASR source fallback for selected American Dad season

[Timer]
OnCalendar=*-*-* 04:30:00
RandomizedDelaySec=20min
Persistent=true
Unit={UNIT}.service

[Install]
WantedBy=timers.target
"""


def ensure_unit(root,name,contents,legacy=None):
    path=root/name
    if path.is_symlink():
        raise RuntimeError('Unsafe unit symlink')
    if path.exists():
        if not path.is_file():
            raise RuntimeError('User systemd unit must be a regular file')
        existing=path.read_text(encoding='utf8')
        if existing==contents:
            return 'unchanged'
        if legacy is None or existing!=legacy:
            raise RuntimeError('Existing distinct systemd unit must not be overwritten')
        # Preserve the exact previously deployed unit before applying a
        # new supervised-only revision. No reload or restart until after.
        backup=root/(name+'.before-supervised.bak')
        if backup.is_symlink():
            raise RuntimeError('Unsafe unit backup symlink')
        if backup.exists():
            if not backup.is_file() or backup.read_text(encoding='utf8')!=legacy:
                raise RuntimeError('Existing unit backup differs')
        else:
            os.link(path,backup,follow_symlinks=False)
        temp=root/(name+'.supervised-'+str(os.getpid())+'.tmp')
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf8') as out:
                out.write(contents)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp,path)
        finally:
            temp.unlink(missing_ok=True)
        return 'upgraded_supervised'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as out:
            out.write(contents)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return 'created'


def enable(home=None,runner=subprocess.run,log=print):
    home=Path(home or Path.home())
    root=home/'.config/systemd/user'
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if root.is_symlink():
        raise RuntimeError('Unsafe user systemd path')
    a=ensure_unit(root,UNIT+'.service',SERVICE,legacy=LEGACY_SERVICE)
    b=ensure_unit(root,UNIT+'.timer',TIMER)
    for cmd in (
        ['systemctl','--user','daemon-reload'],
        ['systemctl','--user','enable','--now',UNIT+'.timer'],
        ['systemctl','--user','is-active',UNIT+'.timer'],
    ):
        result=runner(cmd,capture_output=True,text=True,timeout=30)
        if result.returncode:
            log('AUTO_TIMER_NOT_ACTIVE','systemd_user_unavailable')
            return False
    log('AUTO_TIMER_ACTIVE','04:30_local_nightly','supervised_foreground',
        'one_cpu_only_ASR_episode_per_run','service',a,'timer',b)
    return True


if __name__=='__main__':
    try:
        status=enable()
    except Exception as exc:
        print('AUTO_TIMER_BLOCKED',type(exc).__name__,file=sys.stderr)
        status=False
    raise SystemExit(0 if status else 1)
