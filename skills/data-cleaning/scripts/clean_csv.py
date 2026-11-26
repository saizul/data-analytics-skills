#!/usr/bin/env python3
"""Clean a CSV export: trim, blank null tokens, normalise numbers and dates, dedupe.

Numbers: Bangla/Devanagari digits to ASCII, lakh/crore grouping ("1,00,000") and western
grouping removed, currency symbols (Tk, BDT, $) dropped, "(300)" -> -300, "1.5 lakh" ->
150000, "12.5%" -> 0.125. Dates: day-first or month-first, named months and YYYYMMDD to ISO
8601. Duplicates: exact rows or by key columns, compared after normalisation.

Dry run by default: prints what would change. Writes only with --out (never over the input).
Exit codes: 0 = ok, 1 = --strict and unparseable values or ragged rows remain, 2 = error.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import datetime

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


def to_snake(name: str) -> str:
    s = re.sub(r"[^\w]+", "_", name.strip().lower(), flags=re.UNICODE)
    return re.sub(r"_+", "_", s).strip("_") or "column"


def format_number(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.10f}".rstrip("0").rstrip(".")


def format_date(dt: datetime, has_time: bool) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if has_time else dt.strftime("%Y-%m-%d")


def detect_columns(header: list[str], rows: list[list[str]], order: str, decimal_comma: bool):
    """Guess number and date columns: >= 80% of non-null values parse, and not leading-zero codes."""
    numbers, dates = [], []
    for j, name in enumerate(header):
        values = [r[j].strip() for r in rows if j < len(r) and r[j].strip().lower() not in NULL_TOKENS]
        if not values:
            continue
        if sum(1 for v in values if re.match(r"^0\d+$", v.translate(DIGITS))) > len(values) / 2:
            continue
        n_num = sum(1 for v in values if parse_number(v, decimal_comma) is not None)
        n_date = sum(1 for v in values if not re.match(r"^\d+$", v.translate(DIGITS)) and parse_date(v, order))
        if re.search(r"date|day", name, re.I):
            n_date += sum(1 for v in values if re.match(r"^\d{8}$", v.translate(DIGITS)) and parse_date(v))
        if n_date >= 0.8 * len(values) and n_date >= n_num:
            dates.append(name)
        elif n_num >= 0.8 * len(values):
            numbers.append(name)
    return numbers, dates


def clean(
    header: list[str],
    rows: list[list[str]],
    number_cols: list[str] | None = None,
    date_cols: list[str] | None = None,
    order: str = "dmy",
    decimal_comma: bool = False,
    dedupe: str = "exact",
    keys: list[str] | None = None,
    keep: str = "first",
    snake_headers: bool = False,
    trim: bool = True,
    ascii_digits: bool = False,
    case: dict | None = None,
):
    header = [h.strip() for h in header]
    report: dict = {
        "rows_in": len(rows),
        "trimmed_cells": 0,
        "nulls_blanked": 0,
        "digits_converted": 0,
        "numbers": {},
        "dates": {},
        "unparseable": {},
        "ambiguous_dates": 0,
        "ragged_rows": [],
        "duplicates_removed": [],
        "renamed": {},
        "case_changed": 0,
    }
    auto_num, auto_date = detect_columns(header, rows, order, decimal_comma)
    number_cols = auto_num if number_cols is None else number_cols
    date_cols = auto_date if date_cols is None else date_cols
    for name in [*number_cols, *date_cols, *(keys or []), *(case or {})]:
        if name not in header:
            raise ValueError(f"unknown column {name!r}; columns are {header}")
    report["number_columns"], report["date_columns"] = number_cols, date_cols
    idx = {h: j for j, h in enumerate(header)}
    num_idx = {idx[c] for c in number_cols}
    date_idx = {idx[c] for c in date_cols}
    case_idx = {idx[c]: mode for c, mode in (case or {}).items()}
    out_rows = []
    for i, row in enumerate(rows):
        if len(row) != len(header):
            report["ragged_rows"].append(i + 2)
            row = row + [""] * (len(header) - len(row)) if len(row) < len(header) else row
        new = []
        for j, cell in enumerate(row):
            v = cell
            if trim:
                t = re.sub(r"\s{2,}", " ", v.strip())
                if t != v:
                    report["trimmed_cells"] += 1
                v = t
            if v and v.strip().lower() in NULL_TOKENS:
                report["nulls_blanked"] += 1
                v = ""
            if ascii_digits and v.translate(DIGITS) != v:
                report["digits_converted"] += 1
                v = v.translate(DIGITS)
            col = header[j] if j < len(header) else f"extra_{j}"
            if v and j in num_idx:
                x = parse_number(v, decimal_comma)
                if x is None:
                    report["unparseable"].setdefault(col, []).append({"line": i + 2, "value": v})
                else:
                    nv = format_number(x)
                    if nv != v:
                        report["numbers"][col] = report["numbers"].get(col, 0) + 1
                    v = nv
            elif v and j in date_idx:
                parsed = parse_date(v, order)
                if parsed is None:
                    report["unparseable"].setdefault(col, []).append({"line": i + 2, "value": v})
                else:
                    report["ambiguous_dates"] += parsed[2]
                    nv = format_date(parsed[0], parsed[1])
                    if nv != v:
                        report["dates"][col] = report["dates"].get(col, 0) + 1
                    v = nv
            if v and j in case_idx:
                nv = {"title": v.title(), "lower": v.lower(), "upper": v.upper()}[case_idx[j]]
                report["case_changed"] += nv != v
                v = nv
            new.append(v)
        out_rows.append((i + 2, new))
    if dedupe != "none":
        key_idx = [idx[k] for k in keys] if keys else None
        seen: dict = {}
        order_list = out_rows if keep == "first" else list(reversed(out_rows))
        kept = []
        for line, r in order_list:
            k = tuple(r[j] for j in key_idx) if key_idx else tuple(r)
            if key_idx and all(not x for x in k):
                kept.append((line, r))
                continue
            if k in seen:
                report["duplicates_removed"].append({"line": line, "duplicate_of": seen[k]})
                continue
            seen[k] = line
            kept.append((line, r))
        out_rows = kept if keep == "first" else list(reversed(kept))
        report["duplicates_removed"].sort(key=lambda d: d["line"])
    if snake_headers:
        new_header = [to_snake(h) for h in header]
        report["renamed"] = {a: b for a, b in zip(header, new_header) if a != b}
        header = new_header
    report["rows_out"] = len(out_rows)
    return header, [r for _, r in out_rows], report


def render(report: dict, out: str | None) -> str:
    lines = ["# Cleaning report", ""]
    lines.append(f"Rows: {report['rows_in']} in, {report['rows_out']} out")
    lines.append(f"Number columns: {', '.join(report['number_columns']) or '-'}")
    lines.append(f"Date columns: {', '.join(report['date_columns']) or '-'}")
    lines.append("")
    lines.append(f"- Trimmed / collapsed whitespace: {report['trimmed_cells']} cell(s)")
    lines.append(f"- Null tokens blanked (N/A, null, -): {report['nulls_blanked']}")
    if report["digits_converted"]:
        lines.append(f"- Bangla/Devanagari digits converted: {report['digits_converted']} cell(s)")
    for col, n in report["numbers"].items():
        lines.append(f"- `{col}`: {n} number(s) normalised")
    for col, n in report["dates"].items():
        lines.append(f"- `{col}`: {n} date(s) converted to ISO 8601")
    if report["ambiguous_dates"]:
        lines.append(f"- {report['ambiguous_dates']} ambiguous day/month date(s): confirm --date-order")
    if report["case_changed"]:
        lines.append(f"- Case normalised: {report['case_changed']} cell(s)")
    dups = report["duplicates_removed"]
    if dups:
        shown = ", ".join(f"line {d['line']} (= line {d['duplicate_of']})" for d in dups[:5])
        lines.append(f"- Duplicates removed: {len(dups)}: {shown}")
    for a, b in report["renamed"].items():
        lines.append(f"- Header `{a}` -> `{b}`")
    if report["ragged_rows"]:
        lines.append(f"- Rows with wrong field count (check quoting): lines {report['ragged_rows'][:10]}")
    for col, bad in report["unparseable"].items():
        shown = ", ".join(f'"{b["value"]}" (line {b["line"]})' for b in bad[:5])
        lines.append(f"- `{col}`: {len(bad)} value(s) left unchanged, not parseable: {shown}")
    lines.append("")
    lines.append(f"Wrote {out}" if out else "Dry run: nothing written. Add --out cleaned.csv to write the result.")
    return "\n".join(lines) + "\n"


def _cols(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [c.strip() for c in value.split(",") if c.strip()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Clean a CSV: trim, null tokens, numbers (Bangla digits, lakh/crore), ISO dates, dedupe."
    )
    p.add_argument("path", help="input CSV, or - for stdin")
    p.add_argument("--out", help="write the cleaned CSV here (default: dry run, report only)")
    p.add_argument("--delimiter", help="input delimiter (default: sniffed)")
    p.add_argument("--encoding", default="utf-8-sig", help="input encoding (default utf-8-sig)")
    p.add_argument("--number-cols", help="comma-separated number columns (default: auto-detect; '' for none)")
    p.add_argument("--date-cols", help="comma-separated date columns (default: auto-detect; '' for none)")
    p.add_argument("--date-order", choices=["dmy", "mdy"], default="dmy", help="how to read 03/04/2026 (default dmy)")
    p.add_argument("--decimal-comma", action="store_true", help="numbers use 1.234,56 (European style)")
    p.add_argument(
        "--dedupe", choices=["exact", "key", "none"], default="exact", help="duplicate removal (default exact)"
    )
    p.add_argument("--key", help="comma-separated key columns for --dedupe key")
    p.add_argument("--keep", choices=["first", "last"], default="first", help="which duplicate to keep")
    p.add_argument("--snake-headers", action="store_true", help="rename headers to snake_case")
    p.add_argument("--no-trim", action="store_true", help="do not trim or collapse whitespace")
    p.add_argument("--ascii-digits", action="store_true", help="convert Bangla digits in every column (phones, ids)")
    p.add_argument("--case", action="append", default=[], metavar="COL=title|lower|upper", help="normalise case")
    p.add_argument("--excel-bom", action="store_true", help="write UTF-8 with BOM so Excel shows Bangla text")
    p.add_argument("--strict", action="store_true", help="exit 1 if unparseable values or ragged rows remain")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    args = p.parse_args(argv)
    try:
        if args.dedupe == "key" and not args.key:
            raise ValueError("--dedupe key needs --key COLUMNS")
        case = {}
        for item in args.case:
            col, _, mode = item.partition("=")
            if mode not in ("title", "lower", "upper"):
                raise ValueError(f"--case {item!r}: use COL=title, COL=lower or COL=upper")
            case[col.strip()] = mode
        if args.out and args.path != "-" and os.path.abspath(args.out) == os.path.abspath(args.path):
            raise ValueError("--out must be a new file; the input is never overwritten")
        header, rows, delim = read_table(args.path, args.delimiter, args.encoding)
        if not header:
            raise ValueError("no rows found")
        new_header, new_rows, report = clean(
            header,
            rows,
            _cols(args.number_cols),
            _cols(args.date_cols),
            args.date_order,
            args.decimal_comma,
            args.dedupe,
            _cols(args.key) if args.dedupe == "key" else None,
            args.keep,
            args.snake_headers,
            not args.no_trim,
            args.ascii_digits,
            case,
        )
        if args.out:
            with open(args.out, "w", encoding="utf-8-sig" if args.excel_bom else "utf-8", newline="") as fh:
                w = csv.writer(fh, delimiter=delim)
                w.writerow(new_header)
                w.writerows(new_rows)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"out": args.out, **report}, indent=2, ensure_ascii=False))
    else:
        print(render(report, args.out), end="")
    if args.strict and (report["unparseable"] or report["ragged_rows"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
