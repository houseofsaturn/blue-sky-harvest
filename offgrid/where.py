#!/usr/bin/env python3
"""where.py: ask the H2T (MeshCore, USB) where exlo is, and remember it.

Part of Blue Sky Harvest #off-grid. Runs on exlo, no internet needed.

    ~/offgrid/venv/bin/python ~/offgrid/where.py          # read, save, print
    ~/offgrid/venv/bin/python ~/offgrid/where.py --show   # print the saved position only

Saves ~/offgrid/state/where.json. The briefing card (sunrise, moon, tides) reads it.

How "fresh" is decided: the H2T has no clock battery, so its clock is only right when
the GPS has a fix. If the H2T's clock agrees with exlo's (within 2 minutes), the
position is a live GPS one. If not, the H2T may still report an old stored position:
that is kept as a guess but marked not fresh, and a previous fresh fix is never
overwritten by a stale one.
"""
__version__ = "0.1.0"

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

PORT = os.environ.get("H2T_PORT", "/dev/ttyACM0")
STATE = Path(os.environ.get("OFFGRID_STATE", Path.home() / "offgrid" / "state"))
WHERE = STATE / "where.json"
CLOCK_SLACK = 120  # seconds


def load():
    try:
        return json.loads(WHERE.read_text())
    except (OSError, ValueError):
        return None


def save(data):
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = WHERE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(WHERE)


def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "never"


def show(data):
    if not data:
        print("No position saved yet.")
        return
    state = "live GPS fix" if data.get("fresh") else "NOT fresh (old or stored position)"
    print(f"Position: {data['lat']:.5f}, {data['lon']:.5f}  [{state}]")
    print(f"Last fresh fix: {stamp(data.get('fix_time'))}")
    print(f"Last checked:   {stamp(data.get('checked'))}")


async def ask_h2t():
    try:
        from meshcore import MeshCore
    except ImportError:
        sys.exit("meshcore isn't installed. Run: ~/offgrid/venv/bin/pip install meshcore-cli")
    mc = await MeshCore.create_serial(PORT, only_error=True)
    if mc is None:
        sys.exit(f"The H2T didn't answer on {PORT}. Is it plugged in?")
    try:
        info = dict(mc.self_info or {})
        res = await mc.commands.get_time()
        dev_time = (res.payload or {}).get("time") if res else None
    finally:
        await mc.disconnect()
    return info, dev_time


def main():
    ap = argparse.ArgumentParser(description="Where is exlo? (GPS from the H2T)")
    ap.add_argument("--show", action="store_true", help="only print the saved position")
    args = ap.parse_args()

    old = load()
    if args.show:
        show(old)
        return

    info, dev_time = asyncio.run(ask_h2t())
    now = int(time.time())
    lat, lon = info.get("adv_lat"), info.get("adv_lon")
    has_pos = lat is not None and lon is not None and not (lat == 0 and lon == 0)
    clock_ok = dev_time is not None and abs(dev_time - now) <= CLOCK_SLACK
    fresh = has_pos and clock_ok

    if not clock_ok:
        if dev_time is None:
            drift = "unknown"
        else:
            hours = (dev_time - now) / 3600
            drift = f"{hours / 24:+.0f} days" if abs(hours) > 48 else f"{hours:+.1f} h"
        print(f"The H2T's clock is off ({drift}), so no GPS fix right now.")
        print("Give it some sky (windowsill or outside) and try again in 10 minutes.")

    if fresh:
        data = {"lat": round(lat, 5), "lon": round(lon, 5), "fresh": True,
                "fix_time": now, "checked": now, "source": "h2t"}
    elif old:
        data = dict(old, checked=now, fresh=False)
    elif has_pos:
        data = {"lat": round(lat, 5), "lon": round(lon, 5), "fresh": False,
                "fix_time": None, "checked": now, "source": "h2t (stored)"}
    else:
        print("No position at all yet.")
        return

    save(data)
    show(data)


if __name__ == "__main__":
    main()
