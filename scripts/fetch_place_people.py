#!/usr/bin/env python3
"""Download the list of people for one place from the ualosses.org map API.

    python3 scripts/fetch_place_people.py --place Ніжин --oblast "Чернігівська область"
    python3 scripts/fetch_place_people.py --place Бахмут --oblast "Донецька область" --role event

Writes data/people/<slug>_<role>.csv (UTF-8 with BOM) and .xlsx with name, status,
event date, rank, unit, date of birth (from the profile URL) and profile link.
The API returns 50 people per request and each request takes ~10 s, so a town
of 500 people takes about 2-3 minutes.
"""
import argparse
import gzip
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_tables import KATOTTG_REGION  # noqa: E402
from charts import slugify  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
API = "https://ualosses.org/api/map/drilldown/"
STATUS_RU = {"dead": "погиб", "missing": "пропал без вести", "prisoner": "в плену"}
PAUSE = 3.0
UK_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"


def uk_key(name):
    """Sort key for Ukrainian alphabetical order (plain sort puts Є/І/Ї before А)."""
    return [UK_ALPHABET.find(c) if c in UK_ALPHABET else 100 + ord(c) for c in name.lower()]


def write_outputs(rows, out):
    """rows: dicts from the API -> CSV + XLSX next to each other."""
    import pandas as pd

    seen, recs = set(), []
    for r in sorted(rows, key=lambda r: uk_key(r["name"])):
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        m = re.search(r"-(\d{4}-\d\d-\d\d)-", r["url"])
        recs.append({
            "ПІБ": r["name"], "статус": r["status"], "статус_ru": STATUS_RU.get(r["status"], r["status"]),
            "дата_события": r.get("event_date") or "", "дата_рождения": m.group(1) if m else "",
            "звание": r.get("rank") or "", "часть": r.get("unit") or "",
            "профиль": "https://ualosses.org" + r["url"],
        })
    df = pd.DataFrame(recs)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(out.with_suffix(".xlsx"), engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name="people")
        ws = xl.sheets["people"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col, width in zip("ABCDEFGH", (38, 10, 18, 14, 14, 16, 50, 60)):
            ws.column_dimensions[col].width = width
    return len(df)


def find_place(name, oblast, level):
    with gzip.open(ROOT / "data" / "raw" / "places.json.gz", "rt", encoding="utf-8") as fh:
        places = json.load(fh)["places"]
    prefix = {v: k for k, v in KATOTTG_REGION.items()}.get(oblast) if oblast else None
    cand = [p for p in places if p["name"] == name and p["level"] == level]
    if prefix:
        cand = [p for p in cand if (p.get("code") or "").startswith(prefix)] or cand
    if not cand:
        raise SystemExit(f"place not found: {name}")
    return max(cand, key=lambda p: p.get("population") or 0)


def get_page(session, params):
    for attempt in range(1, 7):
        try:
            r = session.get(API, params=params, timeout=120)
            if r.status_code == 200:
                return r.json()
            print(f"  HTTP {r.status_code}, retry {attempt}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  {type(e).__name__}, retry {attempt}", file=sys.stderr)
        time.sleep(PAUSE * 2 ** attempt)
    raise RuntimeError(f"giving up on page {params['page']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", default="Ніжин")
    ap.add_argument("--oblast", default="Чернігівська область")
    ap.add_argument("--level", default="settlement", choices=["settlement", "community", "district", "region"])
    ap.add_argument("--role", default="origin", choices=["origin", "event"])
    args = ap.parse_args()

    place = find_place(args.place, args.oblast, args.level)
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (data analysis script; polite, sequential)", "Accept-Language": "uk"})
    s.cookies.set("django_language", "uk")
    params = {"place_id": place["id"], "place_kind": place["kind"], "role": args.role, "status": "all",
              "page": 1, "page_size": 50, "period": "all"}
    rows, page, pages = [], 1, 1
    while page <= pages:
        params["page"] = page
        d = get_page(s, params)
        pages = d["num_pages"]
        rows.extend(d["results"])
        print(f"page {page}/{pages}: {len(rows)}/{d['count']}")
        page += 1
        time.sleep(PAUSE)

    out_dir = ROOT / "data" / "people"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slugify(place['name'])}_{args.role}.csv"
    n = write_outputs(rows, out)
    print(f"{n} people -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
