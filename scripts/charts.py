#!/usr/bin/env python3
"""Charts for the video (16:9 PNG, 3840x2160, light and dark versions).

    python3 scripts/charts.py                                  # weekly chart + Nizhyn
    python3 scripts/charts.py --place Ніжин --oblast "Чернігівська область"
    python3 scripts/charts.py --place Бахмут --role event       # where losses happened

Output: charts/*.png, and the numbers behind each place chart in
data/tables/place_<slug>_yearly.csv (+ _monthly.csv).
"""
import argparse
import gzip
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
TABLES = ROOT / "data" / "tables"
OUT = ROOT / "charts"

W, H, DPI = 19.2, 10.8, 200  # 3840 x 2160 px
STATUSES = ["dead", "missing", "prisoner"]
LABEL = {"dead": "Погибшие", "missing": "Пропавшие без вести", "prisoner": "Пленные"}

THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "band": "#f0efec",
        "dead": "#2a78d6", "missing": "#eb6834", "prisoner": "#1baf7a",
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "band": "#262624",
        "dead": "#3987e5", "missing": "#d95926", "prisoner": "#199e70",
    },
}

plt.rcParams.update({
    "font.family": ["Inter", "DejaVu Sans"],
    "font.size": 15,
    "axes.titlelocation": "left",
})


def fmt(n):
    return f"{int(round(n)):,}".replace(",", " ")  # thin space as thousands separator


def setup_axes(ax, t):
    ax.set_facecolor(t["surface"])
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])
    ax.spines["bottom"].set_linewidth(1)
    ax.tick_params(colors=t["muted"], labelsize=14, length=0, pad=8)
    ax.yaxis.grid(True, color=t["grid"], linewidth=1)
    ax.set_axisbelow(True)


def legend_row(fig, t, x, y, items, size=16):
    """Swatch + label legend drawn in figure coordinates; text in ink colour."""
    for key, text in items:
        fig.patches.append(Rectangle((x, y - 0.006), 0.010, 0.018, transform=fig.transFigure,
                                     facecolor=t[key], edgecolor="none"))
        tx = fig.text(x + 0.015, y, text, color=t["ink2"], fontsize=size, va="center")
        fig.canvas.draw()
        bb = tx.get_window_extent().transformed(fig.transFigure.inverted())
        x = bb.x1 + 0.025


# ---------------------------------------------------------------- weekly chart
def weekly_chart(theme):
    t = THEMES[theme]
    w = pd.read_csv(TABLES / "national_weekly.csv", parse_dates=["week_start"])
    w = w[w.week_start >= "2022-02-21"].reset_index(drop=True)
    last_day = (w.week_start.max() + pd.Timedelta(days=6)).strftime("%d.%m.%Y")

    fig = plt.figure(figsize=(W, H), dpi=DPI, facecolor=t["surface"])
    ax = fig.add_axes([0.055, 0.12, 0.915, 0.62])
    setup_axes(ax, t)

    width = pd.Timedelta(days=5.6)  # 7-day slot, the rest is the gap between columns
    x = w.week_start + pd.Timedelta(days=3.5)
    bottom = pd.Series(0, index=w.index)
    for s in STATUSES:
        ax.bar(x, w[s], width=width, bottom=bottom, color=t[s], edgecolor=t["surface"], linewidth=0.5)
        bottom = bottom + w[s]

    # incomplete recent weeks: reporting lag
    lag_start = pd.Timestamp("2026-09-28")
    end = w.week_start.max() + pd.Timedelta(days=7)
    ax.axvspan(lag_start, end + pd.Timedelta(days=10), color=t["band"], zorder=0, linewidth=0)
    ymax = 2200
    ax.text(lag_start - pd.Timedelta(days=6), ymax * 0.955, "данные\nещё поступают", ha="right", va="top",
            color=t["muted"], fontsize=13, linespacing=1.15)

    ax.set_xlim(pd.Timestamp("2022-02-14"), end + pd.Timedelta(days=10))
    ax.set_ylim(0, ymax)
    ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(500))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(v)))
    # year boundaries as unlabeled ticks, the year name centred under its visible span
    lo, hi = pd.Timestamp("2022-02-21"), end
    years = range(lo.year, hi.year + 1)
    bounds = [pd.Timestamp(f"{y}-01-01") for y in years if pd.Timestamp(f"{y}-01-01") > lo]
    centres = [max(lo, pd.Timestamp(f"{y}-01-01")) + (min(hi, pd.Timestamp(f"{y + 1}-01-01"))
               - max(lo, pd.Timestamp(f"{y}-01-01"))) / 2 for y in years]
    ax.set_xticks(bounds, [""] * len(bounds))
    ax.set_xticks(centres, [str(y) for y in years], minor=True)
    ax.tick_params(axis="x", which="major", length=10, width=1, color=t["axis"])
    ax.tick_params(axis="x", which="minor", length=0, labelsize=15, labelcolor=t["ink2"], pad=12)

    # selective labels: the peak week and the highest week of each later year
    peak = w.loc[w.total.idxmax()]
    ax.annotate(f"{fmt(peak.total)}\nнеделя 24 февраля 2022", (peak.week_start + pd.Timedelta(days=3.5), peak.total),
                xytext=(14, -2), textcoords="offset points", ha="left", va="top", color=t["ink"], fontsize=14,
                linespacing=1.2)
    for yr in (2023, 2024, 2025):
        sub = w[w.week_start.dt.year == yr]
        r = sub.loc[sub.total.idxmax()]
        ax.annotate(fmt(r.total), (r.week_start + pd.Timedelta(days=3.5), r.total), xytext=(0, 6),
                    textcoords="offset points", ha="center", va="bottom", color=t["ink2"], fontsize=13)

    # headline + legend + source
    total = int(w[STATUSES].sum().sum())
    fig.text(0.055, 0.915, "Задокументированные потери ВСУ по неделям", color=t["ink"], fontsize=34,
             fontweight="semibold", va="baseline")
    fig.text(0.055, 0.87, f"Погибшие, пропавшие без вести и пленные по дате события, с 24.02.2022 по {last_day} — "
             f"{fmt(total)} человек", color=t["ink2"], fontsize=18, va="baseline")
    sums = w[STATUSES].sum()
    legend_row(fig, t, 0.055, 0.8, [(s, f"{LABEL[s]} · {fmt(sums[s])}") for s in STATUSES])
    fig.text(0.055, 0.045, "Источник: UALosses (ualosses.org), выгрузка 25.10.2026. Только поимённо задокументированные "
             "случаи из открытых источников; реальные потери выше. Записи без точной даты не показаны.",
             color=t["muted"], fontsize=13)
    path = OUT / f"weekly_losses_{theme}.png"
    fig.savefig(path, dpi=DPI, facecolor=t["surface"])
    plt.close(fig)
    return path


# ---------------------------------------------------------------- place data
def load_raw(name):
    with gzip.open(RAW / f"{name}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


def place_series(place_name, oblast, role, level):
    places = load_raw("places")["places"]
    facts_doc = load_raw("facts")
    region_prefix = None
    if oblast:
        from build_tables import KATOTTG_REGION  # same mapping as the tables
        region_prefix = {v: k for k, v in KATOTTG_REGION.items()}.get(oblast)
    cand = [i for i, p in enumerate(places) if p["name"] == place_name and p["level"] == level]
    if region_prefix:
        cand = [i for i in cand if (places[i].get("code") or "").startswith(region_prefix)]
    if not cand:
        raise SystemExit(f"place not found: {place_name} ({level}, {oblast})")
    if len(cand) > 1:
        # several places with the same name: take the most populated, report the others
        cand.sort(key=lambda i: -(places[i].get("population") or 0))
        print("several matches, using the most populated:",
              [(places[i]["name"], places[i].get("code"), places[i].get("population")) for i in cand])
    pi = cand[0]
    role_i = facts_doc["roles"].index(role)
    yearly = defaultdict(lambda: defaultdict(int))
    monthly = defaultdict(lambda: defaultdict(int))
    period_total = defaultdict(int)
    for f in facts_doc["facts"]:
        if f[0] != role_i or f[1] != pi:
            continue
        st = facts_doc["statuses"][f[3]]
        cnt = f[5] if len(f) >= 6 else f[4]
        period_total[facts_doc["periods"][f[4]]] += cnt
        key = str(f[2]) if f[2] is not None else ""
        m = re.match(r"(\d{4})(?:-(\d\d))?", key)
        year = m.group(1) if m else "дата неизвестна"
        yearly[year][st] += cnt
        if m and m.group(2) and (".." not in key or key[:7] == key.split("..")[1][:7]):
            monthly[key[:7]][st] += cnt
    def frame(d, col):
        df = pd.DataFrame([{col: k, **{s: v.get(s, 0) for s in STATUSES}} for k, v in d.items()])
        df["total"] = df[STATUSES].sum(axis=1)
        return df.sort_values(col).reset_index(drop=True)
    return places[pi], frame(yearly, "year"), frame(monthly, "month"), dict(period_total)


TRANSLIT = dict(zip("абвгґдеєжзиіїйклмнопрстуфхцчшщьюяыэё",
                    ["a", "b", "v", "h", "g", "d", "e", "ie", "zh", "z", "y", "i", "i", "i", "k", "l", "m", "n", "o",
                     "p", "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "iu", "ia", "y", "e", "e"]))


def slugify(s):
    s = "".join(TRANSLIT.get(c, c) for c in s.lower())
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


# ---------------------------------------------------------------- place card
RU_NAMES = {"Ніжин": "Нежин"}


def place_chart(theme, place, yearly, totals_extra, role, since22):
    t = THEMES[theme]
    name_ru = RU_NAMES.get(place["name"], place["name"])
    tot = yearly[STATUSES].sum()
    total = int(tot.sum())

    # columns: 2014-2021 folded into one, then each year since 2022, then unknown date
    rows = []
    early = yearly[yearly.year.str.fullmatch(r"\d{4}") & (yearly.year < "2022")]
    if len(early):
        rows.append(("2014–2021", *[early[s].sum() for s in STATUSES]))
    for y in ["2022", "2023", "2024", "2025", "2026"]:
        r = yearly[yearly.year == y]
        rows.append((y + ("*" if y == "2026" else ""), *[(r[s].sum() if len(r) else 0) for s in STATUSES]))
    unk = yearly[~yearly.year.str.fullmatch(r"\d{4}")]
    if len(unk) and unk.total.sum() > 0:
        rows.append(("дата\nнеизв.", *[unk[s].sum() for s in STATUSES]))
    cols = pd.DataFrame(rows, columns=["label", *STATUSES])
    cols["total"] = cols[STATUSES].sum(axis=1)

    fig = plt.figure(figsize=(W, H), dpi=DPI, facecolor=t["surface"])
    verb = "уроженцы и жители" if role == "origin" else "погибли, пропали или попали в плен в районе"
    fig.text(0.055, 0.915, f"{name_ru}: потери ВСУ", color=t["ink"], fontsize=34, fontweight="semibold",
             va="baseline")
    fig.text(0.055, 0.87, (f"Военные из города ({place['name']}), задокументированные в базе UALosses" if role == "origin"
                           else f"Случаи, где местом гибели, пропажи или пленения указан {name_ru}"),
             color=t["ink2"], fontsize=18, va="baseline")

    # hero figure + breakdown (left column)
    fig.text(0.055, 0.60, fmt(total), color=t["ink"], fontsize=120, fontweight="semibold", va="baseline")
    fig.text(0.058, 0.545, "человек всего" + (f", из них {fmt(since22)} — после 24.02.2022" if since22 != total else ""),
             color=t["ink2"], fontsize=18, va="baseline")
    y = 0.46
    for s in STATUSES:
        fig.patches.append(Rectangle((0.058, y - 0.007), 0.010, 0.020, transform=fig.transFigure,
                                     facecolor=t[s], edgecolor="none"))
        fig.text(0.075, y, LABEL[s], color=t["ink2"], fontsize=19, va="center")
        fig.text(0.36, y, fmt(tot[s]), color=t["ink"], fontsize=19, va="center", ha="right", fontweight="semibold")
        y -= 0.055
    y -= 0.02
    for label, value in totals_extra:
        fig.text(0.058, y, label, color=t["ink2"], fontsize=17, va="center")
        fig.text(0.36, y, value, color=t["ink"], fontsize=17, va="center", ha="right")
        y -= 0.048

    # yearly stacked columns (right)
    ax = fig.add_axes([0.45, 0.14, 0.52, 0.62])
    setup_axes(ax, t)
    xs = range(len(cols))
    bottom = pd.Series(0, index=cols.index, dtype=float)
    for s in STATUSES:
        ax.bar(xs, cols[s], width=0.5, bottom=bottom, color=t[s], edgecolor=t["surface"], linewidth=1.2)
        bottom = bottom + cols[s]
    for i, v in enumerate(cols.total):
        ax.text(i, v + cols.total.max() * 0.015, fmt(v), ha="center", va="bottom", color=t["ink"], fontsize=17,
                fontweight="semibold")
    ax.set_xticks(list(xs), cols.label)
    ax.tick_params(axis="x", labelsize=16, colors=t["ink2"])
    top = cols.total.max() * 1.15
    ax.set_ylim(0, top)
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(5, integer=True))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(v)))
    ax.set_title("По году события", color=t["ink2"], fontsize=18, pad=14)

    fig.text(0.055, 0.045, "Источник: UALosses (ualosses.org), выгрузка 25.10.2026. Только поимённо задокументированные "
             "случаи; * 2026 — неполный год, последние месяцы ещё пополняются.", color=t["muted"], fontsize=13)
    path = OUT / f"place_{slugify(place['name'])}_{role}_{theme}.png"
    fig.savefig(path, dpi=DPI, facecolor=t["surface"])
    plt.close(fig)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", default="Ніжин", help="settlement name in Ukrainian, as on the site")
    ap.add_argument("--oblast", default="Чернігівська область")
    ap.add_argument("--role", default="origin", choices=["origin", "event"])
    ap.add_argument("--level", default="settlement", choices=["settlement", "community", "district"])
    ap.add_argument("--skip-weekly", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    if not args.skip_weekly:
        for th in THEMES:
            print(weekly_chart(th))

    place, yearly, monthly, periods = place_series(args.place, args.oblast, args.role, args.level)
    slug = slugify(place["name"])
    yearly.to_csv(TABLES / f"place_{slug}_{args.role}_yearly.csv", index=False, encoding="utf-8-sig")
    monthly.to_csv(TABLES / f"place_{slug}_{args.role}_monthly.csv", index=False, encoding="utf-8-sig")
    extra = []
    pop = place.get("population")
    if pop and args.role == "origin":
        since = sum(v for k, v in periods.items() if k == "post_2022")
        extra.append((f"на 10 тыс. жителей (с 2022 г.)", f"{since / pop * 1e4:.0f}".replace(".", ",")))
        extra.append(("население (2022)", fmt(pop)))
    if args.place == "Ніжин" and args.role == "origin":
        tabs = {f: pd.read_csv(TABLES / f"{f}.csv") for f in ("communities_origin", "districts_origin")}
        c = tabs["communities_origin"].query("name == 'Ніжинська міська громада'")
        d = tabs["districts_origin"].query("name == 'Ніжинський район'")
        if len(c):
            extra.append(("Нежинская громада", fmt(c.total.iloc[0])))
        if len(d):
            extra.append(("Нежинский район", fmt(d.total.iloc[0])))
    print(yearly.to_string(index=False))
    for th in THEMES:
        print(place_chart(th, place, yearly, extra, args.role, periods.get("post_2022", 0)))


if __name__ == "__main__":
    main()
