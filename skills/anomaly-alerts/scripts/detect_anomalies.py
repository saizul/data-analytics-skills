#!/usr/bin/env python3
"""Flag anomalies in daily metrics with a rolling median and MAD (robust z-score).

For each day the baseline is the median of the previous --window days (or, with
--seasonal weekly, the same weekday in the previous --window weeks). A day is an anomaly
when |robust z| >= --threshold AND the change versus the baseline is at least --min-change
(relative) and --min-abs (absolute). Missing days inside the range are reported too, since
a gap is often a broken tracker or export. Rows with the same date are summed.

Exit codes: 0 = no anomalies in the reported range, 1 = anomalies found (for cron/CI alerts),
2 = error.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

NULL_TOKENS = {"", "na", "n/a", "null", "none", "nan", "-", "--", "nil", "#n/a", "(not set)"}
DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯०१२३४५६७८९", "01234567890123456789")
SYMBOLS = "৳$€£₹¥"
_CODES = r"(?:bdt|tk\.?|taka|usd|inr|rs\.?|eur|gbp)"
CURRENCY_RE = re.compile(rf"(?i)^{_CODES}\s*|\s*{_CODES}$")
MULTIPLIERS = {
    "k": 1e3,
    "thousand": 1e3,
    "হাজার": 1e3,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "lacs": 1e5,
    "লাখ": 1e5,
    "লক্ষ": 1e5,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "crore": 1e7,
    "crores": 1e7,
    "cr": 1e7,
    "কোটি": 1e7,
}
WESTERN_RE = re.compile(r"^\d{1,3}(,\d{3})+$")
INDIAN_RE = re.compile(r"^\d{1,2}(,\d{2})*,\d{3}$")
PLAIN_NUM_RE = re.compile(r"^\d+(\.\d+)?$|^\.\d+$")
MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}
TIME = r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*([AaPp][Mm])?)?\s*(?:Z|[+-]\d{2}:?\d{2}|UTC)?"
ISO_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})" + TIME + "$")
NUMERIC_DATE_RE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})" + TIME + "$")
COMPACT_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
NAMED_DMY_RE = re.compile(r"^(\d{1,2})[ -]([A-Za-z]{3,9})\.?,?[ -](\d{4})" + TIME + "$")
NAMED_MDY_RE = re.compile(r"^([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4})" + TIME + "$")
SEVERITY = {"low": 1, "medium": 2, "high": 3}


def parse_number(raw: str, decimal_comma: bool = False) -> float | None:
    """Parse '1,00,000', '৳ ১,২৫০', '(1,234.50)', '12.5%', '1.5 lakh'. Returns None if not a number."""
    s = raw.strip().translate(DIGITS).replace(" ", " ")
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    for sym in SYMBOLS:
        s = s.replace(sym, "")
    s = CURRENCY_RE.sub("", s.strip()).strip()
    if s[:1] in "+-":
        neg ^= s[0] == "-"
        s = s[1:].strip()
    pct = s.endswith("%")
    if pct:
        s = s[:-1].strip()
    mult = 1.0
    m = re.match(r"^(.*?\d)\s*([A-Za-zঀ-৿]+)\.?$", s)
    if m and m.group(2).lower() in MULTIPLIERS:
        s, mult = m.group(1).strip(), MULTIPLIERS[m.group(2).lower()]
    if decimal_comma:
        s = s.replace(".", "").replace(" ", "").replace(",", ".")
    elif "," in s:
        whole, dot, frac = s.partition(".")
        if not (WESTERN_RE.match(whole) or INDIAN_RE.match(whole)):
            return None
        s = whole.replace(",", "") + dot + frac
    if not PLAIN_NUM_RE.match(s):
        return None
    value = float(s) * mult
    if pct:
        value /= 100
    return -value if neg else value


def _time(groups) -> tuple[int, int, int, bool]:
    hh, mm, ss, ampm = groups
    if hh is None:
        return 0, 0, 0, False
    h = int(hh)
    if ampm:
        h = h % 12 + (12 if ampm.lower() == "pm" else 0)
    return h, int(mm), int(ss or 0), True


def parse_date(raw: str, order: str = "dmy") -> tuple[datetime, bool, bool] | None:
    """Return (datetime, has_time, ambiguous) or None. order is 'dmy' or 'mdy' for 01/02/2026."""
    s = raw.strip().translate(DIGITS)
    if not s:
        return None
    ambiguous = False
    try:
        m = ISO_RE.match(s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            h, mi, se, has_t = _time(m.groups()[3:7])
            return datetime(y, mo, d, h, mi, se), has_t, False
        m = COMPACT_RE.match(s)
        if m:
            y = int(m.group(1))
            if not 1900 <= y <= 2100:
                return None
            return datetime(y, int(m.group(2)), int(m.group(3))), False, False
        m = NUMERIC_DATE_RE.match(s)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            if a > 12:
                d, mo = a, b
            elif b > 12:
                mo, d = a, b
            else:
                ambiguous = a != b
                d, mo = (a, b) if order == "dmy" else (b, a)
            h, mi, se, has_t = _time(m.groups()[3:7])
            return datetime(y, mo, d, h, mi, se), has_t, ambiguous
        m = NAMED_DMY_RE.match(s)
        if m and m.group(2).lower() in MONTHS:
            h, mi, se, has_t = _time(m.groups()[3:7])
            return datetime(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)), h, mi, se), has_t, False
        m = NAMED_MDY_RE.match(s)
        if m and m.group(1).lower() in MONTHS:
            h, mi, se, has_t = _time(m.groups()[3:7])
            return datetime(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)), h, mi, se), has_t, False
    except ValueError:
        return None
    return None


def read_table(path: str, delimiter: str | None = None, encoding: str = "utf-8-sig"):
    """Return (header, rows, delimiter). path '-' reads stdin."""
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, encoding=encoding, newline="") as fh:
            text = fh.read()
    text = text.lstrip("\ufeff")
    lines = text.split("\n")
    skip = 0
    while skip < len(lines) and lines[skip].startswith("#"):  # GA4-style comment header
        skip += 1
    text = "\n".join(lines[skip:])
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if not rows:
        return [], [], delimiter
    return rows[0], rows[1:], delimiter


DATE_COLS = ["date", "day", "event_date", "order_date", "ds", "timestamp", "created_at"]
MAD_SCALE = 0.6745


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def load_series(header, rows, date_col=None, value_cols=None, order="dmy"):
    by = {norm(h): h for h in header}
    if date_col:
        if date_col not in header:
            raise ValueError(f"column {date_col!r} not found; columns are {header}")
    else:
        date_col = next((by[c] for c in DATE_COLS if c in by), None)
        if not date_col:
            raise ValueError(f"no date column found (use --date-col); columns are {header}")
    idx = {h: j for j, h in enumerate(header)}
    if value_cols:
        for c in value_cols:
            if c not in header:
                raise ValueError(f"column {c!r} not found; columns are {header}")
    else:
        value_cols = []
        for h in header:
            if h == date_col:
                continue
            vals = [r[idx[h]] for r in rows if idx[h] < len(r) and r[idx[h]].strip()]
            if vals and sum(parse_number(v) is not None for v in vals) >= 0.9 * len(vals):
                value_cols.append(h)
        if not value_cols:
            raise ValueError("no numeric metric columns found (use --value-col)")
    series: dict = {c: defaultdict(float) for c in value_cols}
    seen: dict = {c: set() for c in value_cols}
    bad = 0
    for r in rows:
        raw = r[idx[date_col]] if idx[date_col] < len(r) else ""
        parsed = parse_date(raw, order)
        if not parsed:
            bad += 1
            continue
        d = parsed[0].date()
        for c in value_cols:
            cell = r[idx[c]] if idx[c] < len(r) else ""
            v = parse_number(cell) if cell.strip() else None
            if v is not None:
                series[c][d] += v
                seen[c].add(d)
    return date_col, {c: dict(s) for c, s in series.items()}, bad


def score(
    values: dict,
    window: int = 14,
    min_periods: int = 7,
    threshold: float = 3.5,
    min_change: float = 0.2,
    min_abs: float = 0.0,
    seasonal: str = "none",
    direction: str = "both",
) -> list[dict]:
    """Return one record per day (sorted), with expected value, z and anomaly flags."""
    if not values:
        return []
    days = sorted(values)
    out = []
    d = days[0]
    while d <= days[-1]:
        if d not in values:
            out.append({"date": d.isoformat(), "value": None, "missing": True, "anomaly": True, "type": "missing"})
            d += timedelta(days=1)
            continue
        if seasonal == "weekly":
            hist = [
                values[d - timedelta(days=7 * k)] for k in range(1, window + 1) if d - timedelta(days=7 * k) in values
            ]
        else:
            hist = [values[d - timedelta(days=k)] for k in range(1, window + 1) if d - timedelta(days=k) in values]
        x = values[d]
        rec = {"date": d.isoformat(), "value": x, "missing": False, "anomaly": False, "type": None}
        if len(hist) >= min_periods:
            med = statistics.median(hist)
            mad = statistics.median(abs(h - med) for h in hist)
            spread = mad / MAD_SCALE
            if spread == 0:
                spread = 1.2533 * statistics.mean(abs(h - med) for h in hist)
            diff = x - med
            z = diff / spread if spread > 0 else (0.0 if diff == 0 else float("inf") * (1 if diff > 0 else -1))
            rel = diff / abs(med) if med != 0 else None
            rec.update({"expected": med, "z": z, "change": rel, "baseline_days": len(hist)})
            big = abs(z) >= threshold and abs(diff) >= min_abs
            if rel is not None:
                big = big and abs(rel) >= min_change
            wanted = direction == "both" or (direction == "up" and diff > 0) or (direction == "down" and diff < 0)
            if big and wanted:
                rec["anomaly"] = True
                rec["type"] = "spike" if diff > 0 else "drop"
        out.append(rec)
        d += timedelta(days=1)
    return out


def _num(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.2f}"


def alert_line(metric: str, r: dict) -> str:
    if r["type"] == "missing":
        return f"{r['date']} {metric}: no data for this day (export or tracking gap?)"
    ch = "" if r.get("change") is None else f"{abs(r['change']) * 100:.0f}% "
    word = "above" if r["type"] == "spike" else "below"
    z = "inf" if abs(r["z"]) == float("inf") else f"{r['z']:+.1f}"
    return f"{r['date']} {metric}: {_num(r['value'])} is {ch}{word} expected {_num(r['expected'])} (robust z {z})"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rolling-median (MAD) anomaly detection on daily metric CSVs.")
    p.add_argument("path", help="CSV with a date column and one or more numeric metric columns, or - for stdin")
    p.add_argument("--date-col", help="date column (default: auto-detect)")
    p.add_argument("--value-col", action="append", help="metric column (repeatable; default: all numeric columns)")
    p.add_argument("--window", type=int, default=14, help="baseline length in days, or weeks with --seasonal weekly")
    p.add_argument("--min-periods", type=int, default=7, help="baseline points needed before scoring (default 7)")
    p.add_argument("--threshold", type=float, default=3.5, help="robust z-score threshold (default 3.5)")
    p.add_argument("--min-change", type=float, default=0.2, help="minimum relative change, 0.2 = 20%% (default)")
    p.add_argument("--min-abs", type=float, default=0.0, help="minimum absolute change (default 0)")
    p.add_argument("--seasonal", choices=["none", "weekly"], default="none", help="compare with the same weekday")
    p.add_argument("--direction", choices=["both", "up", "down"], default="both", help="which anomalies to report")
    p.add_argument("--last", type=int, help="only report the last N days (alerting); history is still used")
    p.add_argument("--ignore-missing", action="store_true", help="do not report missing days")
    p.add_argument("--format", choices=["markdown", "alert"], default="markdown", help="alert = one line per anomaly")
    p.add_argument("--date-order", choices=["dmy", "mdy"], default="dmy", help="how to read 03/04/2026")
    p.add_argument("--delimiter", help="field delimiter (default: sniffed)")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    if args.seasonal == "weekly" and args.window == 14 and args.min_periods == 7:
        args.window, args.min_periods = 8, 4
    try:
        header, rows, _ = read_table(args.path, args.delimiter)
        if not header:
            raise ValueError("no rows found")
        date_col, series, bad = load_series(header, rows, args.date_col, args.value_col, args.date_order)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    results: dict = {}
    found: list = []
    for metric, values in series.items():
        recs = score(
            values,
            args.window,
            args.min_periods,
            args.threshold,
            args.min_change,
            args.min_abs,
            args.seasonal,
            args.direction,
        )
        if args.last:
            recs = recs[-args.last :]
        if args.ignore_missing:
            recs = [r for r in recs if not r["missing"]]
        results[metric] = recs
        found += [{"metric": metric, **r} for r in recs if r["anomaly"]]
    if args.json:
        print(
            json.dumps(
                {"date_column": date_col, "unparsed_dates": bad, "anomalies": found, "series": results},
                indent=2,
                default=str,
            )
        )
    elif args.format == "alert":
        for a in found:
            print(alert_line(a["metric"], a))
    else:
        days = {r["date"] for recs in results.values() for r in recs}
        span = f"{min(days)} to {max(days)}" if days else "no data"
        print(f"# Anomaly check: {', '.join(series)} ({span})\n")
        mode = "same weekday, " if args.seasonal == "weekly" else ""
        unit = "weeks" if args.seasonal == "weekly" else "days"
        print(
            f"Baseline: median of previous {args.window} {unit} ({mode}MAD z >= {args.threshold}, "
            f"change >= {args.min_change:.0%}).\n"
        )
        if not found:
            print("No anomalies found.")
        else:
            print("| Date | Metric | Value | Expected | Change | Robust z | Type |")
            print("| --- | --- | ---: | ---: | ---: | ---: | --- |")
            for a in found:
                if a["type"] == "missing":
                    print(f"| {a['date']} | {a['metric']} | - | - | - | - | missing day |")
                    continue
                ch = "-" if a.get("change") is None else f"{a['change'] * 100:+.0f}%"
                z = "inf" if abs(a["z"]) == float("inf") else f"{a['z']:+.1f}"
                value, expected = _num(a["value"]), _num(a["expected"])
                print(f"| {a['date']} | {a['metric']} | {value} | {expected} | {ch} | {z} | {a['type']} |")
        if bad:
            print(f"\nNote: {bad} row(s) had unreadable dates and were skipped.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
