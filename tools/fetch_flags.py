#!/usr/bin/env python3
"""Fetch the country flags the plane card shows beside city names into flightscope/data/flags/<cc>.png (lower-case
ISO 3166 alpha-2). Source: flagcdn.com (flag-icons, MIT). Small 80 px wide PNGs, ~100 KB in all; run once, commit the result."""
import json, sys, time, urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "flightscope" / "data" / "flags"
UA = {"User-Agent": "Flightscope-tools/0.1"}

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r: return r.read()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    codes = sorted(c for c in json.loads(get("https://flagcdn.com/en/codes.json")) if len(c) == 2)      # skip us-ca, gb-eng ...
    n = 0
    for c in codes:
        f = OUT / f"{c}.png"
        if f.exists(): continue
        f.write_bytes(get(f"https://flagcdn.com/w80/{c}.png")); n += 1; time.sleep(0.05)
    print(f"{n} downloaded, {len(codes)} flags in {OUT}")

if __name__ == "__main__": sys.exit(main())
