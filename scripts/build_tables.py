#!/usr/bin/env python3
"""Turn the raw ualosses.org aggregates (data/raw/) into analysis-ready tables.

Writes CSV files (UTF-8 with BOM, so Excel opens Cyrillic correctly) into
data/tables/ and one Excel workbook with every table as a sheet:
data/ualosses_tables.xlsx

How the raw "facts" are structured
----------------------------------
facts.json holds pre-aggregated rows
    [role, place_index, date_key, status, period, count(, unit_index)]
  role    - "origin" (where the person is from) or "event" (where they were
            killed / went missing / were captured)
  place   - index into places.json; every person is counted once at EACH level
            (region, district, community, settlement), so never sum across levels
  date    - date of death / disappearance / capture: "YYYY-MM-DD",
            "YYYY" or a range "start..end" when the exact day is unknown
  period  - post_2022 (full-scale invasion), 2014_2021, unknown
  unit    - military unit index, only on rows where the unit is known

National and regional totals use role=origin at oblast level, plus Kyiv and
Sevastopol (which the site keeps only at settlement level): 231,777 of 234,573
records (98.8%). Places of loss use role=event (216,425 records with a known place).
"""
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "tables"
XLSX = ROOT / "data" / "ualosses_tables.xlsx"

STATUSES = ["dead", "missing", "prisoner"]
CITY_REGIONS = ("м. Київ", "м. Севастополь")

# KATOTTG (Ukrainian admin code) prefix -> oblast; used to attach an oblast to
# districts / communities / settlements. Validated against coordinates below.
KATOTTG_REGION = {
    "UA01": "Автономна Республіка Крим", "UA05": "Вінницька область", "UA07": "Волинська область",
    "UA12": "Дніпропетровська область", "UA14": "Донецька область", "UA18": "Житомирська область",
    "UA21": "Закарпатська область", "UA23": "Запорізька область", "UA26": "Івано-Франківська область",
    "UA32": "Київська область", "UA35": "Кіровоградська область", "UA44": "Луганська область",
    "UA46": "Львівська область", "UA48": "Миколаївська область", "UA51": "Одеська область",
    "UA53": "Полтавська область", "UA56": "Рівненська область", "UA59": "Сумська область",
    "UA61": "Тернопільська область", "UA63": "Харківська область", "UA65": "Херсонська область",
    "UA68": "Хмельницька область", "UA71": "Черкаська область", "UA73": "Чернівецька область",
    "UA74": "Чернігівська область", "UA80": "м. Київ", "UA85": "м. Севастополь",
}


def load(name):
    with gzip.open(RAW / f"{name}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


def parse_date_key(key):
    """-> (exact_date or None, month 'YYYY-MM' or None, year int or None, precision)"""
    if key is None:
        return None, None, None, "unknown"
    k = str(key)
    if re.fullmatch(r"\d{4}-\d\d-\d\d", k):
        return k, k[:7], int(k[:4]), "day"
    if re.fullmatch(r"\d{4}", k):
        return None, None, int(k), "year"
    if ".." in k:
        a, b = k.split("..", 1)
        if a[:7] == b[:7] and a:
            return None, a[:7], int(a[:4]), "month"
        if a[:4] == b[:4] and a:
            return None, None, int(a[:4]), "year"
        return None, None, None, "range"
    return None, None, None, "unknown"


def place_region(place, ru_regions):
    code = place.get("code") or ""
    if place["level"] == "region":
        return place["name"]
    if code[:4] in KATOTTG_REGION:
        return KATOTTG_REGION[code[:4]]
    if place["kind"].startswith("russian") and place.get("lat") is not None:
        for r in ru_regions:  # 3 Russian border regions, assign by bounding box
            if r["bbox_south"] <= place["lat"] <= r["bbox_north"] and r["bbox_west"] <= place["lon"] <= r["bbox_east"]:
                return r["name"]
    return None


def wide(df, index):
    """long (index..., status, count) -> wide with one column per status + total"""
    t = df.pivot_table(index=index, columns="status", values="count", aggfunc="sum", fill_value=0)
    for s in STATUSES:
        if s not in t.columns:
            t[s] = 0
    t = t[STATUSES]
    t["total"] = t.sum(axis=1)
    t.columns.name = None
    return t.reset_index()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    places_doc = load("places")
    facts_doc = load("facts")
    places = places_doc["places"]
    roles, statuses, periods = facts_doc["roles"], facts_doc["statuses"], facts_doc["periods"]
    units = facts_doc["units"]
    generated_at = facts_doc["generated_at"]

    ru_regions = [p for p in places if p["kind"] == "russian_region"]
    region_of = [place_region(p, ru_regions) for p in places]

    # sanity check of the KATOTTG mapping: settlement coordinates should sit inside
    # the bounding box of the oblast they were mapped to
    bbox = {p["name"]: p for p in places if p["level"] == "region"}
    checked = inside = 0
    for p, r in zip(places, region_of):
        if p["level"] == "settlement" and r in bbox and p.get("lat") is not None and "bbox_south" in bbox[r]:
            b = bbox[r]
            checked += 1
            inside += b["bbox_south"] <= p["lat"] <= b["bbox_north"] and b["bbox_west"] <= p["lon"] <= b["bbox_east"]
    print(f"KATOTTG->oblast check: {inside}/{checked} settlements inside their oblast's bbox")

    rows = []
    for f in facts_doc["facts"]:
        role, pi, dk, st, per = f[0], f[1], f[2], f[3], f[4]
        cnt = f[5] if len(f) >= 6 else f[4]
        ui = f[6] if len(f) >= 7 else None
        if len(f) < 6:
            per = None
        rows.append((roles[role], pi, dk, statuses[st], periods[per] if per is not None else None, cnt, ui))
    df = pd.DataFrame(rows, columns=["role", "place_idx", "date_key", "status", "period", "count", "unit_idx"])
    df["level"] = df["place_idx"].map(lambda i: places[i]["level"])

    parsed = {k: parse_date_key(k) for k in df["date_key"].unique()}
    df["date"] = df["date_key"].map(lambda k: parsed[k][0])
    df["month"] = df["date_key"].map(lambda k: parsed[k][1])
    df["year"] = df["date_key"].map(lambda k: parsed[k][2])
    df["date_precision"] = df["date_key"].map(lambda k: parsed[k][3])

    tables = {}

    # The site's region level has no row for the cities with special status
    # (Kyiv, Sevastopol), so they are added from the settlement level.
    def region_rows(role):
        base = df[(df.role == role) & (df.level == "region")].copy()
        base["region"] = base["place_idx"].map(lambda i: places[i]["name"])
        cities = df[(df.role == role) & (df.level == "settlement")].copy()
        cities["region"] = cities["place_idx"].map(lambda i: region_of[i])
        cities = cities[cities["region"].isin(CITY_REGIONS)]
        out = pd.concat([base, cities], ignore_index=True)
        out["country"] = out["place_idx"].map(lambda i: "RU" if places[i]["kind"].startswith("russian") else "UA")
        return out

    reg_o = region_rows("origin")
    reg_e = region_rows("event")
    nat = reg_o  # national totals: everyone with a known oblast (or Kyiv/Sevastopol) of origin

    # ---------- national time series ----------
    m = nat.copy()
    m["month"] = m["month"].fillna("дата невідома / unknown")
    tables["national_monthly"] = wide(m, ["month"]).sort_values("month")
    tables["national_yearly"] = wide(nat.assign(year=nat["year"].fillna(-1).astype(int)), ["year"]).replace({"year": {-1: "unknown"}})
    daily = nat[nat["date"].notna()]
    tables["national_daily"] = wide(daily, ["date"]).sort_values("date")
    w = daily.copy()
    d = pd.to_datetime(w["date"])
    w["week_start"] = (d - pd.to_timedelta(d.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    tables["national_weekly"] = wide(w, ["week_start"]).sort_values("week_start")
    tables["date_precision"] = wide(nat, ["date_precision"])

    # ---------- by oblast of origin ----------
    reg_pop = {p["name"]: p.get("population") for p in places if p["level"] == "region"}
    for city in CITY_REGIONS:  # population of the city itself = its largest settlement
        pops = [p.get("population") or 0 for p, r in zip(places, region_of) if r == city and p["level"] == "settlement"]
        reg_pop[city] = max(pops) if pops and max(pops) > 0 else None
    ro = wide(reg_o, ["region"])
    ro_post = wide(reg_o[reg_o.period == "post_2022"], ["region"]).rename(
        columns={s: f"{s}_since_2022" for s in STATUSES + ["total"]}
    )
    ro = ro.merge(ro_post, on="region", how="left")
    ro.insert(1, "population_2022", ro["region"].map(reg_pop))
    ro["dead_since_2022_per_10k"] = (ro["dead_since_2022"] / ro["population_2022"] * 1e4).round(2)
    ro["total_since_2022_per_10k"] = (ro["total_since_2022"] / ro["population_2022"] * 1e4).round(2)
    tables["regions_origin"] = ro.sort_values("total", ascending=False)
    tables["regions_origin_monthly"] = wide(reg_o[reg_o.month.notna()], ["month", "region"]).sort_values(["month", "region"])

    # ---------- by oblast where the loss happened ----------
    tables["regions_event"] = wide(reg_e, ["region", "country"]).sort_values("total", ascending=False)
    tables["regions_event_monthly"] = wide(reg_e[reg_e.month.notna()], ["month", "region"]).sort_values(["month", "region"])

    # ---------- districts / communities / settlements ----------
    def place_table(role, level):
        sub = df[(df.role == role) & (df.level == level)]
        t = wide(sub, ["place_idx"])
        post = wide(sub[sub.period == "post_2022"], ["place_idx"])[["place_idx", "total"]].rename(
            columns={"total": "total_since_2022"}
        )
        t = t.merge(post, on="place_idx", how="left").fillna({"total_since_2022": 0})
        t["total_since_2022"] = t["total_since_2022"].astype(int)
        t.insert(0, "name", t["place_idx"].map(lambda i: places[i]["name"]))
        t.insert(1, "oblast", t["place_idx"].map(lambda i: region_of[i]))
        t.insert(2, "country", t["place_idx"].map(lambda i: "RU" if places[i]["kind"].startswith("russian") else "UA"))
        t["lat"] = t["place_idx"].map(lambda i: places[i].get("lat"))
        t["lon"] = t["place_idx"].map(lambda i: places[i].get("lon"))
        t["population"] = t["place_idx"].map(lambda i: places[i].get("population"))
        t["katottg_code"] = t["place_idx"].map(lambda i: places[i].get("code"))
        if role == "origin":
            pop = t["population"].where(t["population"] > 0)
            t["total_since_2022_per_10k"] = (t["total_since_2022"] / pop * 1e4).round(2)
        return t.drop(columns="place_idx").sort_values("total", ascending=False)

    for role, tag in (("event", "event"), ("origin", "origin")):
        for level, plural in (("district", "districts"), ("community", "communities"), ("settlement", "settlements")):
            tables[f"{plural}_{tag}"] = place_table(role, level)

    # ---------- military units ----------
    unit_rows = nat[nat.unit_idx.notna()].copy()
    unit_rows["unit_idx"] = unit_rows["unit_idx"].astype(int)
    ut = wide(unit_rows, ["unit_idx"])
    ut.insert(0, "unit_uk", ut["unit_idx"].map(lambda i: units[i].get("name_ukrainian")))
    ut.insert(1, "unit_en", ut["unit_idx"].map(lambda i: units[i].get("name")))
    ut.insert(2, "unit_code", ut["unit_idx"].map(lambda i: units[i].get("code")))
    ut["site_total_count"] = ut["unit_idx"].map(lambda i: units[i].get("count"))
    tables["units"] = ut.drop(columns="unit_idx").sort_values("total", ascending=False)

    um = unit_rows[unit_rows.month.notna()]
    um = wide(um, ["month", "unit_idx"])
    um.insert(1, "unit_uk", um["unit_idx"].map(lambda i: units[i].get("name_ukrainian")))
    tables["units_monthly"] = um.drop(columns="unit_idx").sort_values(["month", "total"], ascending=[True, False])

    ue = df[(df.role == "event") & (df.level == "region") & df.unit_idx.notna()].copy()
    ue["unit_idx"] = ue["unit_idx"].astype(int)
    ue["region_of_loss"] = ue["place_idx"].map(lambda i: places[i]["name"])
    ue = wide(ue, ["unit_idx", "region_of_loss"])
    ue.insert(0, "unit_uk", ue["unit_idx"].map(lambda i: units[i].get("name_ukrainian")))
    tables["units_by_region_of_loss"] = ue.drop(columns="unit_idx").sort_values(["unit_uk", "total"], ascending=[True, False])

    # ---------- site statistics page & list filter counts ----------
    stats = json.loads((RAW / "statistics.json").read_text(encoding="utf-8"))
    wk = []
    for series, items in stats["weekly_last_52"].items():
        for it in items:
            wk.append({"week_start": it["start_date"], "week_end": it["end_date"], "series": series, "count": it["count"]})
    if wk:
        tables["site_weekly_last52"] = (
            pd.DataFrame(wk).pivot_table(index=["week_start", "week_end"], columns="series", values="count").reset_index()
        )
        tables["site_weekly_last52"].columns.name = None
    tables["site_age_distribution"] = pd.DataFrame(stats["age_distribution"])
    tables["site_status_breakdown"] = pd.DataFrame(stats["status_breakdown"])
    rank_file = RAW / "rank_by_status.json"
    rank_total = None
    if rank_file.exists():
        rk = json.loads(rank_file.read_text(encoding="utf-8"))
        rank_total = rk.get("total_in_database")
        r = pd.DataFrame(rk["rows"]).pivot_table(index="rank_type", columns="casualty_type", values="count", aggfunc="sum")
        r = r.reindex(["officers", "nco", "enlisted", "unknown"])[STATUSES]
        r["total"] = r.sum(axis=1)
        r.columns.name = None
        tables["rank_by_status"] = r.reset_index()

    # ---------- write ----------
    meta = pd.DataFrame(
        [
            ("source", "https://ualosses.org (UALosses, open-source documented Ukrainian military losses)"),
            ("site_data_generated_at", generated_at),
            ("statistics_fetched_at", stats.get("fetched_at")),
            ("national tables", "role=origin, oblast level + Kyiv/Sevastopol; covers people with a known home oblast"),
            ("total in database (list page)", rank_total),
            ("national coverage", f"{int(nat['count'].sum())} people"),
            ("regions_origin coverage", f"{int(reg_o['count'].sum())} people with a known oblast of origin"),
            ("regions_event coverage", f"{int(reg_e['count'].sum())} people with a known oblast of loss"),
            ("note", "Only documented, named losses; recent weeks are always incomplete because of reporting lag."),
        ],
        columns=["key", "value"],
    )
    tables = {"README": meta, **tables}
    for name, t in tables.items():
        if name == "README":
            continue
        t.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(XLSX, engine="openpyxl") as xl:
        for name, t in tables.items():
            t.to_excel(xl, sheet_name=name[:31], index=False)
            ws = xl.sheets[name[:31]]
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in list(col)[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
    for name, t in tables.items():
        print(f"{name:28s} {len(t):>7} rows")
    print(f"national coverage: {int(nat['count'].sum())}")


if __name__ == "__main__":
    main()
