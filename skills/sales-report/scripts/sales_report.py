#!/usr/bin/env python3
"""Sales report from an orders CSV: revenue, orders, AOV, customers, repeat rate, top products.

Works with one row per order or one row per line item (rows sharing an order id are
combined). Columns are detected from common names (order_id, order_date, customer_id,
product, quantity, price, total, status) or set with --*-col options. Cancelled, refunded,
failed and voided orders are excluded by default. Amounts may use Bangla digits, lakh/crore
grouping and currency symbols. Customer identifiers are never printed.

Output: Markdown (default) or --json. Exit codes: 0 = ok, 2 = error (missing columns, no rows).
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


CANDIDATES = {
    "order": ["order_id", "order_number", "order_no", "order", "invoice_id", "invoice", "name", "id"],
    "date": ["order_date", "date", "created_at", "created", "ordered_at", "paid_at", "timestamp", "datetime"],
    "customer": ["customer_id", "customer", "customer_email", "email", "phone", "user_id", "buyer", "client"],
    "product": ["product", "product_name", "item", "item_name", "sku", "lineitem_name", "title", "product_title"],
    "quantity": ["quantity", "qty", "units", "lineitem_quantity", "item_quantity"],
    "price": ["unit_price", "price", "lineitem_price", "item_price", "rate"],
    "amount": ["line_total", "amount", "total", "revenue", "sales", "net_sales", "subtotal", "grand_total", "value"],
    "status": ["status", "order_status", "financial_status", "payment_status", "state"],
}
DEFAULT_EXCLUDE = {"cancelled", "canceled", "refunded", "failed", "voided", "void", "returned", "declined"}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def detect(header: list[str], overrides: dict) -> dict:
    by_norm = {norm(h): h for h in header}
    cols = {}
    for role, names in CANDIDATES.items():
        if overrides.get(role):
            if overrides[role] not in header:
                raise ValueError(f"column {overrides[role]!r} not found; columns are {header}")
            cols[role] = overrides[role]
            continue
        cols[role] = next((by_norm[n] for n in names if n in by_norm), None)
    if not cols["date"]:
        raise ValueError(f"no date column found (use --date-col); columns are {header}")
    if not cols["amount"] and not cols["price"]:
        raise ValueError(f"no amount/total or price column found (use --amount-col); columns are {header}")
    if cols["price"] and cols["amount"] and not overrides.get("price"):
        if overrides.get("amount") or not cols["quantity"]:
            cols["price"] = None
        else:
            cols["amount"] = None
    return cols


def period_key(d: date, period: str) -> date:
    if period == "day":
        return d
    if period == "week":
        return d - timedelta(days=d.weekday())
    return d.replace(day=1)


def next_period(d: date, period: str) -> date:
    if period == "day":
        return d + timedelta(days=1)
    if period == "week":
        return d + timedelta(days=7)
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def label(d: date, period: str) -> str:
    if period == "month":
        return d.strftime("%Y-%m")
    if period == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d} ({d.isoformat()})"
    return d.isoformat()


def build_orders(header, rows, cols, order_fmt="dmy", exclude=DEFAULT_EXCLUDE, start=None, end=None):
    idx = {h: j for j, h in enumerate(header)}

    def get(row, role):
        c = cols.get(role)
        if not c:
            return ""
        j = idx[c]
        return row[j].strip() if j < len(row) else ""

    orders: dict = {}
    skipped = {"excluded_status": 0, "bad_date": 0, "bad_amount": 0, "outside_range": 0}
    examples: list = []
    # Shopify-style exports fill order-level fields (status) only on the first line item.
    order_status: dict = {}
    if cols.get("status") and cols.get("order"):
        for row in rows:
            oid, st = get(row, "order"), get(row, "status").lower()
            if oid and st and oid not in order_status:
                order_status[oid] = st
    for i, row in enumerate(rows):
        status = get(row, "status").lower() or order_status.get(get(row, "order"), "")
        if status and status in exclude:
            skipped["excluded_status"] += 1
            continue
        parsed = parse_date(get(row, "date"), order_fmt)
        if not parsed:
            skipped["bad_date"] += 1
            examples.append({"line": i + 2, "problem": "date", "value": get(row, "date")})
            continue
        d = parsed[0].date()
        if (start and d < start) or (end and d > end):
            skipped["outside_range"] += 1
            continue
        qty_raw = get(row, "quantity")
        qty = parse_number(qty_raw) if qty_raw else 1.0
        if cols.get("price"):
            price = parse_number(get(row, "price"))
            value = None if price is None or qty is None else price * qty
        else:
            value = parse_number(get(row, "amount"))
        if value is None or qty is None:
            skipped["bad_amount"] += 1
            examples.append({"line": i + 2, "problem": "amount", "value": get(row, "amount") or get(row, "price")})
            continue
        oid = get(row, "order") or f"row-{i + 2}"
        o = orders.setdefault(oid, {"date": d, "customer": get(row, "customer"), "revenue": 0.0, "units": 0.0})
        o["date"] = min(o["date"], d)
        o["revenue"] += value
        o["units"] += qty
        o.setdefault("lines", []).append((get(row, "product"), qty, value))
        if not o["customer"]:
            o["customer"] = get(row, "customer")
    return orders, skipped, examples[:10]


def report(orders: dict, period: str = "month", top: int = 10) -> dict:
    if not orders:
        raise ValueError("no valid orders after filtering")
    by_customer: dict = defaultdict(list)
    for o in orders.values():
        if o["customer"]:
            by_customer[o["customer"]].append(o["date"])
    first_seen = {c: min(ds) for c, ds in by_customer.items()}
    revenue = sum(o["revenue"] for o in orders.values())
    n_orders = len(orders)
    customers = len(by_customer)
    repeat = sum(1 for ds in by_customer.values() if len(ds) >= 2)
    dates = [o["date"] for o in orders.values()]
    summary = {
        "from": min(dates).isoformat(),
        "to": max(dates).isoformat(),
        "revenue": revenue,
        "orders": n_orders,
        "aov": revenue / n_orders,
        "units": sum(o["units"] for o in orders.values()),
        "customers": customers,
        "repeat_customers": repeat,
        "repeat_rate": repeat / customers if customers else None,
        "orders_per_customer": (sum(len(v) for v in by_customer.values()) / customers if customers else None),
        "orders_without_customer": sum(1 for o in orders.values() if not o["customer"]),
    }
    buckets: dict = defaultdict(lambda: {"revenue": 0.0, "orders": 0, "units": 0.0, "customers": set(), "new": set()})
    for o in orders.values():
        b = buckets[period_key(o["date"], period)]
        b["revenue"] += o["revenue"]
        b["orders"] += 1
        b["units"] += o["units"]
        if o["customer"]:
            b["customers"].add(o["customer"])
            if period_key(first_seen[o["customer"]], period) == period_key(o["date"], period):
                b["new"].add(o["customer"])
    periods = []
    cur, last = min(buckets), max(buckets)
    prev_rev = None
    while cur <= last:
        b = buckets.get(cur, {"revenue": 0.0, "orders": 0, "units": 0.0, "customers": set(), "new": set()})
        change = (b["revenue"] - prev_rev) / prev_rev if prev_rev else None
        periods.append(
            {
                "period": label(cur, period),
                "start": cur.isoformat(),
                "revenue": b["revenue"],
                "orders": b["orders"],
                "aov": b["revenue"] / b["orders"] if b["orders"] else None,
                "units": b["units"],
                "customers": len(b["customers"]),
                "new_customers": len(b["new"]),
                "returning_customers": len(b["customers"]) - len(b["new"]),
                "revenue_change": change,
            }
        )
        prev_rev = b["revenue"]
        cur = next_period(cur, period)
    summary["last_period_complete"] = max(dates) >= next_period(last, period) - timedelta(days=1)
    products: dict = defaultdict(lambda: {"revenue": 0.0, "units": 0.0, "orders": set()})
    for oid, o in orders.items():
        for name, qty, value in o.get("lines", []):
            p = products[name or "(no product)"]
            p["revenue"] += value
            p["units"] += qty
            p["orders"].add(oid)
    ranked = sorted(products.items(), key=lambda kv: (-kv[1]["revenue"], kv[0]))
    top_products = [
        {
            "product": name,
            "revenue": p["revenue"],
            "units": p["units"],
            "orders": len(p["orders"]),
            "share": p["revenue"] / revenue if revenue else None,
        }
        for name, p in ranked[:top]
    ]
    return {"summary": summary, "period": period, "periods": periods, "top_products": top_products}


def money(x: float | None, indian: bool = False, decimals: int = 0) -> str:
    if x is None:
        return "-"
    if not indian:
        return f"{x:,.{decimals}f}"
    neg, x = x < 0, abs(x)
    whole, _, frac = f"{x:.{decimals}f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    s = ",".join([*groups, tail]) if groups else tail
    return ("-" if neg else "") + s + (f".{frac}" if frac else "")


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:+.1f}%" if x < 0 or x > 0 else "0.0%"


def render(r: dict, currency: str = "", indian: bool = False, skipped: dict | None = None) -> str:
    s = r["summary"]
    cur = f"{currency} " if currency else ""

    def m(x, d=0):
        return cur + money(x, indian, d)

    out = [f"# Sales report: {s['from']} to {s['to']}", ""]
    out += ["| Metric | Value |", "| --- | --- |"]
    out.append(f"| Revenue | {m(s['revenue'])} |")
    out.append(f"| Orders | {s['orders']:,} |")
    out.append(f"| Average order value | {m(s['aov'], 2)} |")
    out.append(f"| Units sold | {s['units']:,.0f} |")
    out.append(f"| Customers | {s['customers']:,} |")
    rr = "-" if s["repeat_rate"] is None else f"{s['repeat_rate'] * 100:.1f}% ({s['repeat_customers']} customers)"
    out.append(f"| Repeat customer rate | {rr} |")
    if s["orders_per_customer"]:
        out.append(f"| Orders per customer | {s['orders_per_customer']:.2f} |")
    out += ["", f"## By {r['period']}", ""]
    out.append("| Period | Revenue | Orders | AOV | Customers | New | Returning | Revenue vs previous |")
    out.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for p in r["periods"]:
        out.append(
            f"| {p['period']} | {money(p['revenue'], indian)} | {p['orders']} | {money(p['aov'], indian, 2)} | "
            f"{p['customers']} | {p['new_customers']} | {p['returning_customers']} | {pct(p['revenue_change'])} |"
        )
    out += ["", "## Top products", "", "| # | Product | Revenue | Share | Units | Orders |"]
    out.append("| ---: | --- | ---: | ---: | ---: | ---: |")
    for i, p in enumerate(r["top_products"], 1):
        share = "-" if p["share"] is None else f"{p['share'] * 100:.1f}%"
        out.append(
            f"| {i} | {p['product']} | {money(p['revenue'], indian)} | {share} | {p['units']:,.0f} | {p['orders']} |"
        )
    notes = []
    if skipped:
        if skipped.get("excluded_status"):
            notes.append(f"{skipped['excluded_status']} row(s) excluded by status (cancelled, refunded, ...)")
        if skipped.get("bad_date") or skipped.get("bad_amount"):
            notes.append(
                f"{skipped.get('bad_date', 0)} row(s) with unreadable dates and "
                f"{skipped.get('bad_amount', 0)} with unreadable amounts were skipped"
            )
        if skipped.get("outside_range"):
            notes.append(f"{skipped['outside_range']} row(s) outside --from/--to")
    if s["orders_without_customer"]:
        notes.append(f"{s['orders_without_customer']} order(s) have no customer id (left out of customer metrics)")
    if not s["last_period_complete"]:
        notes.append(f"The last {r['period']} may be incomplete (data ends {s['to']}).")
    if notes:
        out += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Revenue, orders, AOV, repeat rate and top products from an orders CSV.")
    p.add_argument("path", help="orders CSV (one row per order or per line item), or - for stdin")
    p.add_argument("--period", choices=["day", "week", "month"], default="month", help="trend grain (default month)")
    p.add_argument("--top", type=int, default=10, help="number of top products (default 10)")
    p.add_argument("--from", dest="start", help="first date to include (YYYY-MM-DD)")
    p.add_argument("--to", dest="end", help="last date to include (YYYY-MM-DD)")
    p.add_argument("--currency", default="", help="label for amounts, e.g. BDT")
    p.add_argument("--lakh", action="store_true", help="format amounts as 1,00,000 (South Asian grouping)")
    p.add_argument("--date-order", choices=["dmy", "mdy"], default="dmy", help="how to read 03/04/2026")
    p.add_argument("--exclude-status", help="comma-separated statuses to drop (default: cancelled, refunded, ...)")
    p.add_argument("--include-all-statuses", action="store_true", help="do not drop any status")
    for role in ("order", "date", "customer", "product", "quantity", "price", "amount", "status"):
        p.add_argument(f"--{role}-col", help=f"{role} column name (default: auto-detect)")
    p.add_argument("--delimiter", help="field delimiter (default: sniffed)")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        header, rows, _ = read_table(args.path, args.delimiter)
        if not header:
            raise ValueError("no rows found")
        overrides = {role: getattr(args, f"{role}_col") for role in CANDIDATES}
        cols = detect(header, overrides)
        if args.include_all_statuses:
            exclude = set()
        elif args.exclude_status is not None:
            exclude = {s.strip().lower() for s in args.exclude_status.split(",") if s.strip()}
        else:
            exclude = DEFAULT_EXCLUDE
        start = date.fromisoformat(args.start) if args.start else None
        end = date.fromisoformat(args.end) if args.end else None
        orders, skipped, examples = build_orders(header, rows, cols, args.date_order, exclude, start, end)
        result = report(orders, args.period, args.top)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {"columns": cols, "skipped": skipped, "skipped_examples": examples, **result},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(render(result, args.currency, args.lakh, skipped), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
