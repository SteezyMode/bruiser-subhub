#!/usr/bin/env python3
"""Read-only, timestamped OptiPlex telemetry for American Dad's PLaMo batch.

Sidecar monitor: attach to the existing batch process, sample every 15 seconds,
record CSV in a private location, and exit when that batch exits. Does not
change power limits, translation code, model placement, or GPU settings.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time

STATE = Path.home() / "bruiser-pilot/plamo3-ab/american-dad-existing-english-batch"
OUT = STATE / "telemetry"
SCRIPT = b"plamo8b_american_dad_existing_en_batch.py"
EPISODE = re.compile(r"=== EPISODE \d+/\d+: (S\d{2}E\d{2,3}) ===")
# The user reported a 24 W LACT limit on 2026-11-05; this is a label,
# not a power-limit setting, and NVML may report a different board limit.
USER_REPORTED_CAP_W = 24.0
INTERVAL = 15
FIELDS = [
    "utc", "batch_pid", "episode", "cues_done", "cues_total",
    "cpu_package_c", "gpu_c", "gpu_power_draw_w",
    "gpu_driver_reported_limit_w", "user_reported_cap_w",
    "gpu_util_pct", "vram_used_mib", "vram_total_mib",
    "ram_used_mib", "ram_total_mib", "cpu_util_pct", "load_1m",
    "read_error",
]


def batch_pid():
    path = STATE / "batch.pid"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        pid = int(path.read_text("ascii").strip())
        if pid < 2:
            return None
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
        if SCRIPT not in cmd:
            return None
        status = Path(f"/proc/{pid}/status").read_text("ascii", errors="replace")
        uidline = next(x for x in status.splitlines() if x.startswith("Uid:"))
        if int(uidline.split()[1]) != os.getuid():
            return None
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError, StopIteration, PermissionError):
        return None


def cpu_temp():
    package = []
    cores = []
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (hw / "name").read_text().strip() != "coretemp":
                continue
        except OSError:
            continue
        for sensor in hw.glob("temp*_input"):
            try:
                v = float(sensor.read_text().strip()) / 1000
                label = sensor.with_name(sensor.name.replace("_input", "_label"))
                name = label.read_text().strip() if label.exists() else ""
                if 0 < v < 120:
                    (package if "Package" in name else cores).append(v)
            except (OSError, ValueError):
                pass
    if package or cores:
        return max(package or cores)
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            name = (zone / "type").read_text().strip().lower()
            if name in ("x86_pkg_temp", "cpu-thermal", "cpu_thermal"):
                v = float((zone / "temp").read_text().strip()) / 1000
                if 0 < v < 120:
                    return v
        except (OSError, ValueError):
            pass
    return None


def value(text):
    cleaned = str(text).strip()
    if cleaned.lower() in ("n/a", "none", "not supported", ""):
        return None
    match = re.match(r"^-?\d+(?:\.\d+)?", cleaned)
    return float(match.group()) if match else None


def gpu_stats():
    # All read-only, independent of LACT/NVIDIA power-cap configuration.
    columns = ("temperature.gpu,power.draw,power.limit,"
               "utilization.gpu,memory.used,memory.total")
    cmd = ["nvidia-smi", "--query-gpu=" + columns,
           "--format=csv,noheader,nounits"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=8, check=True)
        parts = proc.stdout.splitlines()[0].split(",")
        if len(parts) != 6:
            raise ValueError("unexpected_gpu_field_count")
        return [value(item) for item in parts], ""
    except (OSError, subprocess.SubprocessError, IndexError, ValueError) as exc:
        return [None] * 6, "gpu_" + type(exc).__name__


def memory():
    items = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, amount = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                items[key] = int(amount.split()[0]) / 1024
        total, available = items["MemTotal"], items["MemAvailable"]
        return round(total - available, 1), round(total, 1)
    except (OSError, ValueError, KeyError, IndexError):
        return None, None


def cpu_ticks():
    try:
        values = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        ticks = [int(v) for v in values]
        return sum(ticks), ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    except (OSError, ValueError, IndexError):
        return None


def cpu_percent(before, after):
    if not before or not after:
        return None
    elapsed = after[0] - before[0]
    if elapsed <= 0:
        return None
    return round(100 * (1 - (after[1] - before[1]) / elapsed), 1)


def episode_and_cues():
    log = STATE / "batch.log"
    if not log.is_file() or log.is_symlink():
        return "", None, None
    try:
        with log.open("rb") as handle:
            n = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, n - 15000))
            tail = handle.read().decode("utf-8", "replace")
        tags = EPISODE.findall(tail)
        if not tags:
            return "", None, None
        tag = tags[-1]
        for folder in sorted(STATE.glob(tag + "-*")):
            if folder.is_symlink():
                continue
            manifest = folder / "episode.json"
            db = folder / "progress.sqlite3"
            if not manifest.is_file() or manifest.is_symlink():
                continue
            import json
            obj = json.loads(manifest.read_text("utf-8"))
            if obj.get("episode") != tag:
                continue
            total = int(obj.get("cue_count", 0))
            if not 0 < total <= 1500:
                continue
            if not db.is_file() or db.is_symlink():
                return tag, 0, total
            with sqlite3.connect(db.as_uri() + "?mode=ro",
                                 uri=True, timeout=1) as con:
                completed = con.execute(
                    "SELECT COUNT(*) FROM translation").fetchone()[0]
            return tag, min(completed, total), total
        return tag, None, None
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        return "", None, None


def sample(pid, prior):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current = cpu_ticks()
    cpu_pct = cpu_percent(prior, current)
    gpu, error = gpu_stats()
    ram_used, ram_total = memory()
    try:
        load = round(os.getloadavg()[0], 2)
    except OSError:
        load = None
    tag, done, total = episode_and_cues()
    vals = [
        now, pid, tag, done, total, cpu_temp(), gpu[0], gpu[1], gpu[2],
        USER_REPORTED_CAP_W, gpu[3], gpu[4], gpu[5], ram_used, ram_total,
        cpu_pct, load, error,
    ]
    return dict(zip(FIELDS, vals)), current


def monitor(interval=INTERVAL):
    pid = batch_pid()
    if pid is None:
        print("No running American Dad translation batch to monitor.")
        return 2
    if OUT.is_symlink():
        raise RuntimeError("telemetry_directory_symlink")
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if OUT.stat().st_mode & 0o077:
        raise RuntimeError("telemetry_directory_not_private")
    lock = OUT / ".monitor.lock"
    if lock.is_symlink():
        raise RuntimeError("telemetry_lock_symlink")
    with lock.open("a+b") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Telemetry monitor already running; leaving it alone.")
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = OUT / f"session-{stamp}-batch{pid}.csv"
        if path.exists() or path.is_symlink():
            raise RuntimeError("telemetry_file_name_collision")
        with path.open("x", newline="", encoding="utf-8") as output:
            os.chmod(path, 0o600)
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            output.flush()
            print(f"Recording 15-second hardware telemetry: {path}", flush=True)
            last = cpu_ticks()
            count = 0
            while batch_pid() == pid and count < 100000:
                row, last = sample(pid, last)
                writer.writerow(row)
                output.flush()
                count += 1
                time.sleep(interval)
            os.fsync(output.fileno())
        print(f"Telemetry complete: {count} samples -> {path}", flush=True)
    return 0


def summarize():
    paths = sorted(OUT.glob("session-*.csv")) if OUT.is_dir() else []
    if not paths:
        print("No hardware telemetry sessions recorded yet.")
        return
    rows = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    if not rows:
        print("No telemetry samples available.")
        return
    print(f"American Dad hardware telemetry: {len(rows)} samples, "
          f"{len(paths)} session file(s)")
    print("Sample interval: 15 sec; user-reported starting GPU cap: 24 W")
    for field, name, unit in [
        ("cpu_package_c", "CPU package", "°C"),
        ("gpu_c", "GPU temperature", "°C"),
        ("gpu_power_draw_w", "GPU power draw", "W"),
        ("gpu_util_pct", "GPU utilization", "%"),
        ("vram_used_mib", "VRAM used", "MiB"),
        ("ram_used_mib", "Host RAM used", "MiB"),
        ("cpu_util_pct", "Host CPU use", "%"),
    ]:
        vals = [value(r.get(field) or "") for r in rows]
        vals = [x for x in vals if x is not None]
        if vals:
            print(f"  {name}: avg {sum(vals)/len(vals):.1f}{unit}, "
                  f"peak {max(vals):.1f}{unit}")
    by_episode = {}
    for r in rows:
        tag = r.get("episode", "")
        if tag:
            by_episode.setdefault(tag, []).append(r)
    print(f"Episodes observed: {len(by_episode)}")
    for tag, samples in list(by_episode.items())[:100]:
        c = [value(r.get("cpu_package_c") or "") for r in samples]
        g = [value(r.get("gpu_c") or "") for r in samples]
        c = [x for x in c if x is not None]
        g = [x for x in g if x is not None]
        print(f"  {tag}: {len(samples)} samples; "
              f"CPU peak {max(c) if c else 'N/A'}°C; "
              f"GPU peak {max(g) if g else 'N/A'}°C")
    print(f"Raw CSV: {OUT}/session-*.csv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.add_mutually_exclusive_group(required=True)
    args.add_argument("--monitor", action="store_true")
    args.add_argument("--once", action="store_true")
    args.add_argument("--summary", action="store_true")
    opts = parser.parse_args()
    if opts.summary:
        summarize()
    elif opts.once:
        row, _ = sample(batch_pid(), cpu_ticks())
        import json
        print(json.dumps(row, ensure_ascii=False, indent=2))
    else:
        raise SystemExit(monitor())


if __name__ == "__main__":
    main()
