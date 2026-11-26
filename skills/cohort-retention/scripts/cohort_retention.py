#!/usr/bin/env python3
"""Cohort retention table from an orders or activity CSV (monthly or weekly cohorts).

Each user's cohort is the period of their first order/activity in the file. Retention in
period N = share of the cohort active again N periods later. Cells that are not observable
yet are left blank (not 0), and the last, partial period is marked. Optional --value-col
adds revenue per cohort member (cumulative LTV). Cancelled/refunded rows are dropped when a
status column exists.

Output: Markdown (default), --format csv, or --json. Exit codes: 0 = ok, 2 = error.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

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


USER_COLS = ["customer_id", "user_id", "customer", "user", "client_id", "email", "customer_email", "phone", "buyer"]
DATE_COLS = ["order_date", "date", "created_at", "created", "event_date", "activity_date", "timestamp", "ordered_at"]
STATUS_COLS = ["status", "order_status", "financial_status", "payment_status"]
EXCLUDE = {"cancelled", "canceled", "refunded", "failed", "voided", "void", "returned", "declined"}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def pick(header: list[str], wanted: str | None, candidates: list[str], role: str, required: bool = True):
    if wanted:
        if wanted not in header:
            raise ValueError(f"column {wanted!r} not found; columns are {header}")
        return wanted
    by_norm = {norm(h): h for h in header}
    for c in candidates:
        if c in by_norm:
            return by_norm[c]
    if required:
        raise ValueError(f"no {role} column found (use --{role}-col); columns are {header}")
    return None


def period_index(d: date, period: str) -> int:
    if period == "week":
        return (d.toordinal() - 1) // 7  # weeks start on Monday (date(1, 1, 1) is a Monday)
    return d.year * 12 + d.month - 1


def period_start(idx: int, period: str) -> date:
    if period == "week":
        return date.fromordinal(idx * 7 + 1)
    return date(idx // 12, idx % 12 + 1, 1)


def period_label(idx: int, period: str) -> str:
    d = period_start(idx, period)
    if period == "week":
        return d.isoformat()
    return d.strftime("%Y-%m")


def load_events(header, rows, user_col, date_col, status_col=None, value_col=None, order="dmy"):
    idx = {h: j for j, h in enumerate(header)}
    events, skipped = [], {"no_user": 0, "bad_date": 0, "excluded_status": 0, "bad_value": 0}

    def cell(row, col):
        j = idx[col]
        return row[j].strip() if j < len(row) else ""

    for row in rows:
        if status_col and cell(row, status_col).lower() in EXCLUDE:
            skipped["excluded_status"] += 1
            continue
        user = cell(row, user_col)
        if not user or user.lower() in NULL_TOKENS:
            skipped["no_user"] += 1
            continue
        parsed = parse_date(cell(row, date_col), order)
        if not parsed:
            skipped["bad_date"] += 1
            continue
        value = 0.0
        if value_col:
            v = parse_number(cell(row, value_col))
            if v is None:
                skipped["bad_value"] += 1
                v = 0.0
            value = v
        events.append((user.lower() if "@" in user else user, parsed[0].date(), value))
    return events, skipped


def cohorts(events, period: str = "month", max_periods: int = 12, min_size: int = 1) -> dict:
    if not events:
        raise ValueError("no usable rows (check the user and date columns)")
    first: dict = {}
    for user, d, _ in events:
        p = period_index(d, period)
        if user not in first or p < first[user]:
            first[user] = p
    active: dict = defaultdict(set)  # (cohort, offset) -> users
    value: dict = defaultdict(float)
    for user, d, v in events:
        c = first[user]
        off = period_index(d, period) - c
        active[(c, off)].add(user)
        value[(c, off)] += v
    last_day = max(d for _, d, _ in events)
    last_idx = period_index(last_day, period)
    nxt = period_start(last_idx + 1, period)
    last_complete = last_day >= nxt - timedelta(days=1)
    sizes: dict = defaultdict(int)
    for c in first.values():
        sizes[c] += 1
    table = []
    for c in sorted(sizes):
        size = sizes[c]
        if size < min_size:
            continue
        observable = min(last_idx - c, max_periods)
        retention, counts, ltv = [], [], []
        cum = 0.0
        for off in range(observable + 1):
            n = len(active.get((c, off), ()))
            counts.append(n)
            retention.append(n / size)
            cum += value.get((c, off), 0.0)
            ltv.append(cum / size)
        table.append(
            {
                "cohort": period_label(c, period),
                "size": size,
                "active": counts,
                "retention": retention,
                "value_per_user": ltv,
                "last_cell_partial": not last_complete and c + observable == last_idx,
            }
        )
    width = max((len(r["retention"]) for r in table), default=0)
    weighted = []
    for off in range(width):
        rows = [
            r
            for r in table
            if len(r["retention"]) > off and not (r["last_cell_partial"] and off == len(r["retention"]) - 1)
        ]
        denom = sum(r["size"] for r in rows)
        weighted.append(sum(r["active"][off] for r in rows) / denom if denom else None)
    return {
        "period": period,
        "users": len(first),
        "last_date": last_day.isoformat(),
        "last_period_complete": last_complete,
        "cohorts": table,
        "weighted_average": weighted,
    }


def render_markdown(res: dict, show_value: bool = False, currency: str = "") -> str:
    p = "M" if res["period"] == "month" else "W"
    width = len(res["weighted_average"])
    out = [f"# Cohort retention ({res['period']}ly cohorts)", ""]
    out.append(f"{res['users']:,} users in {len(res['cohorts'])} cohorts; data ends {res['last_date']}.")
    out.append("")
    head = ["Cohort", "Users"] + [f"{p}{i}" for i in range(width)]
    out.append("| " + " | ".join(head) + " |")
    out.append("| --- | ---: |" + " ---: |" * width)
    for r in res["cohorts"]:
        cells = []
        for i in range(width):
            if i < len(r["retention"]):
                mark = "*" if r["last_cell_partial"] and i == len(r["retention"]) - 1 else ""
                cells.append(f"{r['retention'][i] * 100:.0f}%{mark}")
            else:
                cells.append("")
        out.append(f"| {r['cohort']} | {r['size']} | " + " | ".join(cells) + " |")
    avg = ["-" if x is None else f"{x * 100:.0f}%" for x in res["weighted_average"]]
    out.append("| **Weighted avg** | | " + " | ".join(avg) + " |")
    if any(r["last_cell_partial"] for r in res["cohorts"]):
        out += ["", f"`*` = the current {res['period']} is not finished; excluded from the average."]
    if show_value:
        cur = f" ({currency})" if currency else ""
        out += ["", f"## Cumulative revenue per user{cur}", ""]
        out.append("| " + " | ".join(head) + " |")
        out.append("| --- | ---: |" + " ---: |" * width)
        for r in res["cohorts"]:
            cells = [f"{v:,.0f}" for v in r["value_per_user"]] + [""] * (width - len(r["value_per_user"]))
            out.append(f"| {r['cohort']} | {r['size']} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def render_csv(res: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    width = len(res["weighted_average"])
    w.writerow(["cohort", "users"] + [f"period_{i}" for i in range(width)])
    for r in res["cohorts"]:
        w.writerow(
            [r["cohort"], r["size"]] + [f"{x:.4f}" for x in r["retention"]] + [""] * (width - len(r["retention"]))
        )
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Monthly or weekly cohort retention table from an orders/activity CSV.")
    p.add_argument("path", help="CSV with one row per order or activity, or - for stdin")
    p.add_argument("--period", choices=["month", "week"], default="month", help="cohort grain (default month)")
    p.add_argument("--max-periods", type=int, default=12, help="columns after the first period (default 12)")
    p.add_argument("--min-size", type=int, default=1, help="hide cohorts smaller than this (default 1)")
    p.add_argument("--user-col", help="user/customer id column (default: auto-detect)")
    p.add_argument("--date-col", help="date column (default: auto-detect)")
    p.add_argument("--status-col", help="status column; cancelled/refunded rows are dropped (default: auto-detect)")
    p.add_argument("--value-col", help="amount column: adds cumulative revenue per user (LTV) per cohort")
    p.add_argument("--currency", default="", help="label for --value-col amounts")
    p.add_argument("--date-order", choices=["dmy", "mdy"], default="dmy", help="how to read 03/04/2026")
    p.add_argument("--format", choices=["markdown", "csv"], default="markdown", help="text output format")
    p.add_argument("--delimiter", help="field delimiter (default: sniffed)")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        header, rows, _ = read_table(args.path, args.delimiter)
        if not header:
            raise ValueError("no rows found")
        user_col = pick(header, args.user_col, USER_COLS, "user")
        date_col = pick(header, args.date_col, DATE_COLS, "date")
        status_col = pick(header, args.status_col, STATUS_COLS, "status", required=False)
        value_col = pick(header, args.value_col, [], "value", required=False) if args.value_col else None
        events, skipped = load_events(header, rows, user_col, date_col, status_col, value_col, args.date_order)
        res = cohorts(events, args.period, args.max_periods, args.min_size)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    res["skipped"] = skipped
    res["columns"] = {"user": user_col, "date": date_col, "status": status_col, "value": value_col}
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    elif args.format == "csv":
        print(render_csv(res), end="")
    else:
        print(render_markdown(res, bool(value_col), args.currency), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
