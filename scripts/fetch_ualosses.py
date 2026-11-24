#!/usr/bin/env python3
"""Download the aggregated loss data that ualosses.org publishes for its map
and statistics pages.

Saves everything into data/raw/:
  places.json.gz        - every place (oblast / district / community / settlement)
                          with coordinates and population
  facts.json.gz         - pre-aggregated counts:
                          role (origin|event) x place x date x status x period [x unit]
  statistics.json       - weekly counts for the last 52 weeks, age buckets,
                          status breakdown (parsed from /en/statistics/)
  rank_by_status.json   - counts for every casualty_type x rank_type filter
                          combination of the soldiers list (optional, slow)

The site is run by volunteers and its filtered queries are slow (~10 s each),
so requests are sequential with a pause between them.

Usage:
    python3 scripts/fetch_ualosses.py              # map data + statistics
    python3 scripts/fetch_ualosses.py --rank-counts  # also the 12 slow list queries
"""
import argparse
import gzip
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://ualosses.org"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
HEADERS = {"User-Agent": "Mozilla/5.0 (data analysis script; polite, sequential)"}
PAUSE = 2.0  # seconds between requests


def get(session, url, *, retries=5, timeout=120, **kw):
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            print(f"  HTTP {r.status_code} for {url} (attempt {attempt})", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  {type(e).__name__} for {url} (attempt {attempt})", file=sys.stderr)
        time.sleep(PAUSE * 2 ** attempt)  # 4, 8, 16, 32, 64 s
    raise RuntimeError(f"giving up on {url}")


def save_gz_json(session, name):
    url = f"{BASE}/static/precomputed/map/data/{name}.json"
    print(f"GET {url}")
    r = get(session, url)
    data = r.json()  # validate before writing
    out = RAW / f"{name}.json.gz"
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"  -> {out.relative_to(RAW.parent.parent)} (generated_at {data.get('generated_at')})")
    time.sleep(PAUSE)


def fetch_statistics(session):
    url = f"{BASE}/en/statistics/"
    print(f"GET {url}")
    h = get(session, url).text
    m = re.search(r'<script[^>]*id="weeklyCasualtyData"[^>]*>(.*?)</script>', h, flags=re.S)
    weekly = json.loads(m.group(1)) if m else {}
    for series in weekly.values():
        for row in series:
            row.pop("height", None)
            row.pop("height_css", None)
    age = [
        {"age_group": g, "count": int(c)}
        for g, c in re.findall(
            r'<div class="stats-age-row"><span>([^<]+)</span>.*?<strong>(\d+)</strong>', h, flags=re.S
        )
    ]
    status = [
        {"status": s, "count": int(c), "share": p}
        for s, c, p in re.findall(
            r'<article class="stats-status-card"><span>([^<]+)</span><strong>(\d+)</strong>.*?<small>([^<]+)</small>',
            h,
            flags=re.S,
        )
    ]
    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": url,
        "weekly_last_52": weekly,
        "age_distribution": age,
        "status_breakdown": status,
    }
    (RAW / "statistics.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  -> data/raw/statistics.json ({len(age)} age groups, {len(status)} statuses)")
    time.sleep(PAUSE)


def fetch_rank_counts(session):
    """Total found for each casualty_type x rank_type filter of the soldiers list."""
    rows = []
    for ct in ("dead", "missing", "prisoner"):
        for rt, label in (("O", "officers"), ("N", "nco"), ("E", "enlisted"), ("U", "unknown")):
            url = f"{BASE}/uk/soldiers/"
            r = get(session, url, params={"casualty_type": ct, "rank_type": rt}, headers={**HEADERS, "HX-Request": "true"})
            m = re.search(r"Знайдено:</b>\s*(\d+)", r.text)
            n = int(m.group(1)) if m else None
            print(f"  {ct:9s} {label:9s} {n}")
            rows.append({"casualty_type": ct, "rank_type": label, "count": n})
            time.sleep(PAUSE)
    total = get(session, f"{BASE}/uk/soldiers/", headers={**HEADERS, "HX-Request": "true"}).text
    m = re.search(r"Знайдено:</b>\s*(\d+)", total)
    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_in_database": int(m.group(1)) if m else None,
        "rows": rows,
    }
    (RAW / "rank_by_status.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  -> data/raw/rank_by_status.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank-counts", action="store_true", help="also run the 12 slow casualty x rank list queries")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update(HEADERS)
    save_gz_json(s, "places")
    save_gz_json(s, "facts")
    fetch_statistics(s)
    if args.rank_counts:
        fetch_rank_counts(s)


if __name__ == "__main__":
    main()
