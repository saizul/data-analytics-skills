#!/usr/bin/env python3
"""Profile a CSV file: column types, nulls, uniques, numeric stats, IQR outliers, date ranges.

Read-only. Python 3.8+ standard library only. Understands Bangla digits, lakh/crore
grouping ("1,00,000"), currency symbols (Tk, BDT, $) and percentages when inferring
numbers, and day-first or month-first dates.

Exit codes: 0 = profiled (no issue at or above --fail-on), 1 = issues found, 2 = error.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
from collections import Counter
from datetime import date, datetime

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


def classify(value: str, header: str, order: str) -> str:
    v = value.strip()
    low = v.lower()
    if low in ("true", "false", "yes", "no"):
        return "boolean"
    digits = v.translate(DIGITS)
    if re.match(r"^0\d+$", digits):
        return "code"
    if re.match(r"^\d{8}$", digits) and re.search(r"date|day", header, re.I) and parse_date(v):
        return "date"
    if parse_number(v) is not None:
        return "integer" if re.match(r"^[+-]?\d+$", digits) else "number"
    parsed = parse_date(v, order)
    if parsed:
        return "datetime" if parsed[1] else "date"
    return "string"


def _fmt(x: float) -> str:
    if x == int(x) and abs(x) < 1e15:
        return f"{int(x):,}"
    return f"{x:,.4g}" if abs(x) < 1 else f"{x:,.2f}"


def profile_column(name: str, values: list[str], order: str, today: date, max_top: int, redact: bool = False) -> dict:
    total = len(values)
    nulls = [i for i, v in enumerate(values) if v.strip().lower() in NULL_TOKENS]
    null_set = set(nulls)
    present = [(i, v) for i, v in enumerate(values) if i not in null_set]
    kinds = Counter(classify(v, name, order) for _, v in present)
    col: dict = {
        "name": name,
        "count": total,
        "nulls": len(nulls),
        "null_pct": round(100 * len(nulls) / total, 1) if total else 0.0,
        "unique": len({v.strip() for _, v in present}),
        "kinds": dict(kinds),
        "issues": [],
    }
    if not present:
        col["type"] = "empty"
        col["issues"].append(("medium", "column is empty"))
        return col
    numeric = kinds["integer"] + kinds["number"]
    dates = kinds["date"] + kinds["datetime"]
    groups = {"numeric": numeric, "date": dates, "boolean": kinds["boolean"], "code": kinds["code"]}
    groups["string"] = kinds["string"]
    dominant = max(groups, key=lambda k: groups[k])
    if dominant == "numeric":
        col["type"] = "integer" if kinds["number"] == 0 else "number"
    elif dominant == "date":
        col["type"] = "datetime" if kinds["datetime"] else "date"
    else:
        col["type"] = dominant
    if dominant == "string" and kinds["code"] and kinds["string"] < kinds["code"] * 4:
        col["type"] = "code"
    col["candidate_key"] = col["unique"] == len(present) == total and total > 1

    if col["type"] in ("integer", "number"):
        nums, bad = [], []
        for i, v in present:
            x = parse_number(v)
            if x is None:
                bad.append((i, v))
            else:
                nums.append((i, x))
        if bad:
            col["issues"].append(("medium", f"{len(bad)} value(s) are not numeric, e.g. {_examples(bad, redact)}"))
        xs = [x for _, x in nums]
        col["stats"] = _numeric_stats(xs)
        if len(xs) >= 8:
            q1, _, q3 = statistics.quantiles(xs, n=4, method="inclusive")
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            out = [(i, x) for i, x in nums if x < lo or x > hi]
            col["outliers"] = {
                "low_fence": lo,
                "high_fence": hi,
                "count": len(out),
                "examples": [{"line": i + 2, "value": x} for i, x in out[:5]],
            }
            if out:
                col["issues"].append(
                    ("low", f"{len(out)} IQR outlier(s) outside [{_fmt(lo)}, {_fmt(hi)}], e.g. {_examples(out)}")
                )
        if any(re.search(r"[,৳$€£₹%]|tk|bdt", v, re.I) for _, v in present) or any(
            v.translate(DIGITS) != v for _, v in present
        ):
            col["issues"].append(
                ("low", "numbers are stored as formatted text (separators, currency or Bangla digits)")
            )
    elif col["type"] in ("date", "datetime"):
        parsed, bad, ambiguous = [], [], 0
        for i, v in present:
            p = parse_date(v, order)
            if p is None:
                bad.append((i, v))
            else:
                parsed.append(p[0])
                ambiguous += p[2]
        if bad:
            col["issues"].append(("medium", f"{len(bad)} value(s) are not dates, e.g. {_examples(bad, redact)}"))
        days = {d.date() for d in parsed}
        lo, hi = min(days), max(days)
        span = (hi - lo).days + 1
        col["dates"] = {
            "min": lo.isoformat(),
            "max": hi.isoformat(),
            "span_days": span,
            "distinct_days": len(days),
            "missing_days": span - len(days),
            "future": sum(1 for d in days if d > today),
            "ambiguous_day_month": ambiguous,
            "formats": len({_shape(v) for _, v in present}),
        }
        if ambiguous:
            col["issues"].append(
                ("medium", f"{ambiguous} date(s) like 03/04/2026 are ambiguous; read as {order.upper()}")
            )
        if col["dates"]["formats"] > 1:
            col["issues"].append(("low", f"{col['dates']['formats']} different date formats are mixed"))
        if col["dates"]["future"]:
            col["issues"].append(("low", f"{col['dates']['future']} date(s) are after {today.isoformat()}"))
    else:
        lengths = [len(v) for _, v in present]
        col["text"] = {"min_len": min(lengths), "max_len": max(lengths)}
    raw = [v for _, v in present]
    top = Counter(v.strip() for v in raw).most_common(max_top)
    col["top"] = [] if redact and col["type"] in ("string", "code") else [{"value": v, "count": c} for v, c in top]
    ws = sum(1 for v in raw if v != v.strip() or "  " in v)
    if ws:
        col["issues"].append(("low", f"{ws} value(s) have leading/trailing or double spaces"))
    if col["type"] in ("string", "boolean"):
        variants: dict[str, set] = {}
        for v in raw:
            variants.setdefault(v.strip().lower(), set()).add(v.strip())
        multi = [sorted(s) for s in variants.values() if len(s) > 1]
        if multi:
            example = "(hidden)" if redact else " / ".join(multi[0][:3])
            col["issues"].append(("low", f"{len(multi)} value(s) differ only by case, e.g. {example}"))
    mixed = len(present) - max(groups.values())
    if (
        mixed
        and col["type"] not in ("code",)
        and not any("not numeric" in m or "not dates" in m for _, m in col["issues"])
    ):
        col["issues"].append(("medium", f"mixed types: {dict(kinds)}"))
    if col["unique"] == 1 and total > 1:
        col["issues"].append(("low", "constant column (one distinct value)"))
    if col["null_pct"] >= 50:
        col["issues"].append(("medium", f"{col['null_pct']}% null"))
    if col["type"] == "code":
        col["issues"].append(("low", "digits with leading zeros (phone, postcode, id): keep as text"))
    return col


def _shape(v: str) -> str:
    return re.sub(r"[A-Za-z]+", "a", re.sub(r"\d", "9", v.strip().translate(DIGITS)))


def _examples(items, redact: bool = False) -> str:
    if redact:
        return ", ".join(f"line {i + 2}" for i, _ in items[:3])
    return ", ".join(
        f'"{v}" (line {i + 2})' if isinstance(v, str) else f"{_fmt(v)} (line {i + 2})" for i, v in items[:3]
    )


def _numeric_stats(xs: list[float]) -> dict:
    if not xs:
        return {}
    out = {
        "min": min(xs),
        "max": max(xs),
        "sum": sum(xs),
        "mean": statistics.fmean(xs) if hasattr(statistics, "fmean") else statistics.mean(xs),
        "median": statistics.median(xs),
        "stdev": statistics.stdev(xs) if len(xs) > 1 else 0.0,
        "zeros": sum(1 for x in xs if x == 0),
        "negatives": sum(1 for x in xs if x < 0),
    }
    if len(xs) >= 2:
        q1, _, q3 = statistics.quantiles(xs, n=4, method="inclusive")
        out["p25"], out["p75"] = q1, q3
    return out


def profile(
    header: list[str],
    rows: list[list[str]],
    order: str = "dmy",
    today: date | None = None,
    max_top: int = 5,
    redact: bool = False,
):
    today = today or date.today()
    width = len(header)
    issues: list[dict] = []
    ragged = [i for i, r in enumerate(rows) if len(r) != width]
    if ragged:
        issues.append(
            {
                "severity": "high",
                "column": None,
                "message": f"{len(ragged)} row(s) have a different number of fields than the header "
                f"(first at line {ragged[0] + 2})",
            }
        )
    dup_headers = [h for h, c in Counter(h.strip() for h in header).items() if c > 1]
    if dup_headers:
        issues.append({"severity": "high", "column": None, "message": f"duplicate column names: {dup_headers}"})
    if any(not h.strip() for h in header):
        issues.append({"severity": "medium", "column": None, "message": "blank column name(s)"})
    norm = [tuple(c.strip() for c in r) for r in rows]
    dupes = sum(c - 1 for c in Counter(norm).values() if c > 1)
    if dupes:
        issues.append({"severity": "medium", "column": None, "message": f"{dupes} exact duplicate row(s)"})
    columns = []
    for j, name in enumerate(header):
        values = [r[j] if j < len(r) else "" for r in rows]
        col = profile_column(name.strip() or f"column_{j + 1}", values, order, today, max_top, redact)
        for sev, msg in col.pop("issues"):
            issues.append({"severity": sev, "column": col["name"], "message": msg})
        columns.append(col)
    return {"rows": len(rows), "columns": len(header), "duplicate_rows": dupes, "fields": columns, "issues": issues}


def summary_cell(col: dict) -> str:
    if "stats" in col and col["stats"]:
        s = col["stats"]
        return f"min {_fmt(s['min'])}, median {_fmt(s['median'])}, max {_fmt(s['max'])}, mean {_fmt(s['mean'])}"
    if "dates" in col:
        d = col["dates"]
        extra = f", {d['missing_days']} day(s) without rows" if d["missing_days"] else ""
        return f"{d['min']} to {d['max']} ({d['span_days']} days{extra})"
    top = ", ".join(f"{t['value']} ({t['count']})" for t in col.get("top", [])[:3])
    return f"top: {top}" if top else ""


def render(name: str, result: dict, delimiter: str) -> str:
    out = [f"# Profile: {name}", ""]
    out.append(
        f"Rows: {result['rows']:,} | Columns: {result['columns']} | Delimiter: {delimiter!r} | "
        f"Duplicate rows: {result['duplicate_rows']}"
    )
    out += ["", "## Columns", "", "| Column | Type | Nulls | Unique | Summary |", "| --- | --- | --- | --- | --- |"]
    for c in result["fields"]:
        key = " (key)" if c.get("candidate_key") else ""
        nulls = f"{c['nulls']} ({c['null_pct']}%)"
        out.append(f"| {c['name']} | {c['type']}{key} | {nulls} | {c['unique']} | {summary_cell(c)} |")
    out += ["", "## Issues", ""]
    if not result["issues"]:
        out.append("No issues found.")
    for i in sorted(result["issues"], key=lambda x: -SEVERITY[x["severity"]]):
        where = f"`{i['column']}`: " if i["column"] else ""
        out.append(f"- [{i['severity']}] {where}{i['message']}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Profile a CSV: types, nulls, uniques, outliers, date ranges.")
    p.add_argument("path", help="CSV file, or - for stdin")
    p.add_argument("--delimiter", help="field delimiter (default: sniffed from , ; tab |)")
    p.add_argument("--encoding", default="utf-8-sig", help="file encoding (default utf-8-sig)")
    p.add_argument("--date-order", choices=["dmy", "mdy"], default="dmy", help="how to read 03/04/2026 (default dmy)")
    p.add_argument("--today", help="reference date for 'future date' checks (YYYY-MM-DD, default today)")
    p.add_argument("--top", type=int, default=5, help="top values per column (default 5)")
    p.add_argument(
        "--fail-on",
        choices=["low", "medium", "high", "none"],
        default="none",
        help="exit 1 if an issue at or above this severity exists (default none)",
    )
    p.add_argument("--redact", action="store_true", help="hide text values (names, phones) in top values and examples")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        header, rows, delim = read_table(args.path, args.delimiter, args.encoding)
        today = date.fromisoformat(args.today) if args.today else None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not header:
        print("error: no rows found", file=sys.stderr)
        return 2
    result = profile(header, rows, args.date_order, today, args.top, args.redact)
    if args.json:
        print(json.dumps({"file": args.path, "delimiter": delim, **result}, indent=2, ensure_ascii=False))
    else:
        print(render(args.path, result, delim), end="")
    if args.fail_on != "none" and any(SEVERITY[i["severity"]] >= SEVERITY[args.fail_on] for i in result["issues"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
