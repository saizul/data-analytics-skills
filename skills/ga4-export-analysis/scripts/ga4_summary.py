#!/usr/bin/env python3
"""Summarise Google Analytics 4 exports offline: sessions, sources, landing pages, conversions.

Inputs:
  * GA4 report CSV downloaded from the UI (Share > Download file > CSV): the '#' comment
    header, one or more tables, Date columns as YYYYMMDD. Additive metrics are totalled;
    rates (engagement rate, key event rate) are recomputed from the totals instead of summed.
  * GA4 BigQuery export events as newline-delimited JSON or a JSON array (one object per
    event: event_date, event_timestamp, event_name, user_pseudo_id, event_params, ...).
    Sessions are user_pseudo_id + ga_session_id; landing page = first page_view/session_start
    page_location; source/medium = session_traffic_source_last_click, else collected_traffic_source,
    else event_params source/medium, else '(direct) / (none)'.

Read-only, no network. Exit codes: 0 = ok, 2 = error.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urlsplit

DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
METRICS = {
    "sessions": ["sessions"],
    "users": ["total users", "users", "active users"],
    "new_users": ["new users"],
    "engaged_sessions": ["engaged sessions"],
    "key_events": ["key events", "conversions"],
    "revenue": ["total revenue", "purchase revenue", "revenue", "ecommerce revenue"],
    "views": ["views", "screen page views", "screen_page_views"],
    "event_count": ["event count"],
    "transactions": ["transactions", "ecommerce purchases", "purchases"],
}
NON_ADDITIVE_RE = re.compile(r"rate|average|avg|per |duration|ratio|%|time", re.I)
TIME_DIM_RE = re.compile(r"^(date|date \+ hour.*|day|week|month|year|hour|nth .*|iso week.*)$", re.I)
SKIP_FIRST_CELLS = {"grand total", "total", "totals"}


def num(s: str) -> float | None:
    s = s.strip().translate(DIGITS).replace(",", "")
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100
        except ValueError:
            return None
    s = re.sub(r"^[^\d.+-]+", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def canonical(header: str) -> str | None:
    h = header.strip().lower()
    for key, names in METRICS.items():
        for n in names:
            if h == n or (key == "key_events" and h.startswith(n + " (")) or (key == "revenue" and h == n + " (usd)"):
                return key
    return None


def parse_ga4_csv(text: str) -> tuple[dict, list[dict]]:
    meta: dict = {}
    tables: list[dict] = []
    cur = None
    for line in text.lstrip("\ufeff").splitlines():
        if line.startswith("#"):
            m = re.match(r"#\s*(Start date|End date)\s*:\s*(\d{8})", line, re.I)
            if m:
                meta["start" if m.group(1).lower().startswith("start") else "end"] = _ymd(m.group(2))
            elif not meta.get("title") and line.strip("#- ").strip() and ":" in line and "Account" not in line:
                meta["title"] = line.strip("#- ").strip()
            if cur:
                tables.append(cur)
                cur = None
            continue
        if not line.strip():
            if cur:
                tables.append(cur)
                cur = None
            continue
        row = next(csv.reader([line]))
        if cur is None:
            cur = {"header": [h.strip() for h in row], "rows": []}
        else:
            cur["rows"].append(row)
    if cur:
        tables.append(cur)
    return meta, [t for t in tables if t["rows"]]


def _ymd(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if re.match(r"^\d{8}$", s) else s


def summarise_table(table: dict, top: int = 10) -> dict:
    header, rows = table["header"], table["rows"]
    metrics, dims = [], []
    for j, h in enumerate(header):
        vals = [r[j] for r in rows if j < len(r) and r[j].strip()]
        numeric = vals and sum(num(v) is not None for v in vals) >= 0.9 * len(vals)
        if canonical(h) or (numeric and not TIME_DIM_RE.match(h)):
            metrics.append(j)
        else:
            dims.append(j)
    clean_rows = []
    for r in rows:
        r = r + [""] * (len(header) - len(r))
        first = r[dims[0]].strip().lower() if dims else ""
        if first in SKIP_FIRST_CELLS or (dims and all(not r[j].strip() for j in dims)):
            continue
        clean_rows.append(r)
    canon = {j: canonical(header[j]) for j in metrics}
    additive = [j for j in metrics if canon[j] != "users" and not NON_ADDITIVE_RE.search(header[j])]
    totals = {header[j]: sum(num(r[j]) or 0.0 for r in clean_rows) for j in additive}
    by_key = {canon[j]: header[j] for j in metrics if canon[j]}
    derived = _derived({k: totals.get(v) for k, v in by_key.items()})
    sort_col = by_key.get("sessions") or (header[additive[0]] if additive else None)
    items = []
    for r in clean_rows:
        values = {header[j]: num(r[j]) for j in metrics}
        item = {"dimension": " / ".join(r[j].strip() for j in dims) or "(all)", "metrics": values}
        item["derived"] = _derived({k: values.get(v) for k, v in by_key.items()})
        items.append(item)
    is_time = bool(dims) and all(TIME_DIM_RE.match(header[j]) for j in dims)
    if is_time:
        for it in items:
            it["dimension"] = _ymd(it["dimension"])
        items.sort(key=lambda it: it["dimension"])
        shown = items
    else:
        items.sort(key=lambda it: -(it["metrics"].get(sort_col) or 0) if sort_col else 0)
        shown = items[:top]
    total_sort = totals.get(sort_col) if sort_col else None
    for it in shown:
        v = it["metrics"].get(sort_col) if sort_col else None
        it["share"] = v / total_sort if total_sort and v is not None else None
    return {
        "dimensions": [header[j] for j in dims],
        "metrics": [header[j] for j in metrics],
        "rows": len(clean_rows),
        "totals": totals,
        "derived": derived,
        "non_additive": [header[j] for j in metrics if j not in additive],
        "time_series": is_time,
        "sorted_by": sort_col,
        "items": shown,
    }


def _derived(m: dict) -> dict:
    out = {}
    s = m.get("sessions")
    if s:
        if m.get("engaged_sessions") is not None:
            out["engagement_rate"] = m["engaged_sessions"] / s
        if m.get("key_events") is not None:
            out["key_events_per_session"] = m["key_events"] / s
        if m.get("revenue") is not None:
            out["revenue_per_session"] = m["revenue"] / s
        if m.get("transactions") is not None:
            out["transaction_rate"] = m["transactions"] / s
    return out


# ---------- BigQuery export ----------


def iter_events(text: str):
    t = text.lstrip("\ufeff").strip()
    if not t:
        return
    if t.startswith("["):
        yield from json.loads(t)
        return
    for n, line in enumerate(t.splitlines(), 1):
        if line.strip():
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {n}: invalid JSON ({exc.msg})") from exc


def params(ev: dict) -> dict:
    out = {}
    for p in ev.get("event_params") or []:
        v = p.get("value") or {}
        for k in ("string_value", "int_value", "double_value", "float_value"):
            if v.get(k) is not None:
                out[p.get("key")] = v[k]
                break
    return out


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def source_medium(ev: dict, prm: dict) -> str | None:
    last = (ev.get("session_traffic_source_last_click") or {}).get("manual_campaign") or {}
    if last.get("source"):
        return f"{last['source']} / {last.get('medium') or '(none)'}"
    col = ev.get("collected_traffic_source") or {}
    if col.get("manual_source"):
        return f"{col['manual_source']} / {col.get('manual_medium') or '(none)'}"
    if col.get("gclid"):
        return "google / cpc"
    if prm.get("source"):
        return f"{prm['source']} / {prm.get('medium') or '(none)'}"
    return None


def landing_path(url: str, keep_query: bool) -> str:
    parts = urlsplit(str(url))
    path = parts.path or "/"
    return path + (f"?{parts.query}" if keep_query and parts.query else "")


def summarise_events(events, conversions=("purchase",), keep_query=False, top=10) -> dict:
    conv = set(conversions)
    sessions: dict = {}
    users, names = set(), Counter()
    no_session = 0
    page_views = 0
    for ev in events:
        name = ev.get("event_name", "")
        names[name] += 1
        user = ev.get("user_pseudo_id")
        if user:
            users.add(user)
        prm = params(ev)
        if name == "page_view":
            page_views += 1
        sid = prm.get("ga_session_id")
        if not user or sid is None:
            no_session += 1
            continue
        ts = int(_f(ev.get("event_timestamp")) or 0)
        s = sessions.setdefault(
            (user, str(sid)),
            {
                "ts": ts,
                "date": None,
                "landing": None,
                "landing_ts": None,
                "source": None,
                "source_ts": None,
                "engaged": False,
                "conversions": 0,
                "revenue": 0.0,
                "device": None,
            },
        )
        if ts <= s["ts"] or s["date"] is None:
            s["ts"] = min(ts, s["ts"])
            s["date"] = _ymd(str(ev.get("event_date", ""))) or s["date"]
        if name in ("page_view", "session_start") and prm.get("page_location"):
            if s["landing_ts"] is None or ts < s["landing_ts"]:
                s["landing"], s["landing_ts"] = landing_path(prm["page_location"], keep_query), ts
        sm = source_medium(ev, prm)
        if sm and (s["source_ts"] is None or ts < s["source_ts"]):
            s["source"], s["source_ts"] = sm, ts
        if str(prm.get("session_engaged", "")) == "1":
            s["engaged"] = True
        dev = (ev.get("device") or {}).get("category")
        if dev and not s["device"]:
            s["device"] = dev
        if name in conv:
            s["conversions"] += 1
            if name == "purchase":
                ec = ev.get("ecommerce") or {}
                rev = _f(ec.get("purchase_revenue"))
                if rev is None:
                    rev = _f(ev.get("event_value_in_usd"))
                if rev is None:
                    rev = _f(prm.get("value"))
                s["revenue"] += rev or 0.0
    for s in sessions.values():
        s["source"] = s["source"] or "(direct) / (none)"
        s["landing"] = s["landing"] or "(not set)"
        s["device"] = s["device"] or "(not set)"
    n = len(sessions)
    engaged = sum(s["engaged"] for s in sessions.values())
    conv_sessions = sum(1 for s in sessions.values() if s["conversions"])
    totals = {
        "users": len(users),
        "sessions": n,
        "engaged_sessions": engaged,
        "engagement_rate": engaged / n if n else None,
        "page_views": page_views,
        "conversions": sum(s["conversions"] for s in sessions.values()),
        "converting_sessions": conv_sessions,
        "session_conversion_rate": conv_sessions / n if n else None,
        "revenue": sum(s["revenue"] for s in sessions.values()),
        "events": sum(names.values()),
        "events_without_session": no_session,
    }
    dates = sorted(s["date"] for s in sessions.values() if s["date"])
    return {
        "from": dates[0] if dates else None,
        "to": dates[-1] if dates else None,
        "conversion_events": sorted(conv),
        "totals": totals,
        "by_source_medium": _group(sessions, "source", top),
        "by_landing_page": _group(sessions, "landing", top),
        "by_device": _group(sessions, "device", top),
        "by_date": sorted(_group(sessions, "date", 10_000), key=lambda g: g["key"]),
        "top_events": [{"event": k, "count": v} for k, v in names.most_common(top)],
    }


def _group(sessions: dict, field: str, top: int) -> list[dict]:
    g: dict = defaultdict(lambda: {"sessions": 0, "engaged": 0, "conv_sessions": 0, "conversions": 0, "revenue": 0.0})
    for s in sessions.values():
        b = g[s[field]]
        b["sessions"] += 1
        b["engaged"] += s["engaged"]
        b["conv_sessions"] += bool(s["conversions"])
        b["conversions"] += s["conversions"]
        b["revenue"] += s["revenue"]
    total = len(sessions) or 1
    out = [
        {
            "key": k,
            "sessions": b["sessions"],
            "share": b["sessions"] / total,
            "engagement_rate": b["engaged"] / b["sessions"],
            "conversions": b["conversions"],
            "conversion_rate": b["conv_sessions"] / b["sessions"],
            "revenue": b["revenue"],
        }
        for k, b in g.items()
    ]
    out.sort(key=lambda r: (-r["sessions"], -r["revenue"], str(r["key"])))
    return out[:top]


# ---------- rendering ----------


def _n(x) -> str:
    if x is None:
        return "-"
    return f"{x:,.0f}" if abs(x) >= 100 or float(x).is_integer() else f"{x:,.2f}"


def _p(x) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def render_events(r: dict) -> str:
    t = r["totals"]
    out = [f"# GA4 summary (BigQuery export): {r['from']} to {r['to']}", ""]
    out += ["| Metric | Value |", "| --- | --- |"]
    out.append(f"| Users | {t['users']:,} |")
    out.append(f"| Sessions | {t['sessions']:,} |")
    out.append(f"| Engaged sessions | {t['engaged_sessions']:,} ({_p(t['engagement_rate'])}) |")
    out.append(f"| Page views | {t['page_views']:,} |")
    out.append(f"| Conversions ({', '.join(r['conversion_events'])}) | {t['conversions']:,} |")
    out.append(f"| Session conversion rate | {_p(t['session_conversion_rate'])} |")
    out.append(f"| Revenue | {_n(t['revenue'])} |")
    for title, key in (
        ("Source / medium", "by_source_medium"),
        ("Landing page", "by_landing_page"),
        ("Device", "by_device"),
    ):
        out += ["", f"## Top {title.lower()}", ""]
        out += [f"| {title} | Sessions | Share | Engagement | Conversions | Conv. rate | Revenue |"]
        out.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for g in r[key]:
            out.append(
                f"| {g['key']} | {g['sessions']:,} | {_p(g['share'])} | {_p(g['engagement_rate'])} | "
                f"{g['conversions']} | {_p(g['conversion_rate'])} | {_n(g['revenue'])} |"
            )
    if len(r["by_date"]) > 1:
        out += ["", "## By date", "", "| Date | Sessions | Conversions | Revenue |", "| --- | ---: | ---: | ---: |"]
        out += [f"| {g['key']} | {g['sessions']:,} | {g['conversions']} | {_n(g['revenue'])} |" for g in r["by_date"]]
    if t["events_without_session"]:
        out += [
            "",
            f"Note: {t['events_without_session']} event(s) had no ga_session_id and are not in session metrics.",
        ]
    return "\n".join(out) + "\n"


def render_tables(meta: dict, results: list[dict]) -> str:
    span = f": {meta['start']} to {meta['end']}" if meta.get("start") and meta.get("end") else ""
    out = [f"# GA4 report summary{span}", ""]
    if meta.get("title"):
        out += [f"Report: {meta['title']}", ""]
    for res in results:
        dim = " / ".join(res["dimensions"]) or "(no dimension)"
        out += [f"## {dim} ({res['rows']} rows)", ""]
        for k, v in res["totals"].items():
            name = k if k.lower().startswith("total") else f"Total {k.lower()}"
            out.append(f"- {name}: {_n(v)}")
        for k, v in res["derived"].items():
            shown = _p(v) if k.endswith("rate") else f"{v:,.3f}" if k == "key_events_per_session" else _n(v)
            out.append(f"- {k.replace('_', ' ').capitalize()}: {shown}")
        if res["non_additive"]:
            out.append(f"- Not totalled (rates, averages or users): {', '.join(res['non_additive'])}")
        cols = _pick_columns(res["metrics"])
        head = [dim, *cols]
        if not res["time_series"]:
            head.append("Share")
        if any("engagement_rate" in it["derived"] for it in res["items"]) and not any(
            "engagement rate" in c.lower() for c in cols
        ):
            head.append("Engagement")
        out += ["", "| " + " | ".join(head) + " |", "|" + " --- |" + " ---: |" * (len(head) - 1)]
        for it in res["items"]:
            cells = [it["dimension"]]
            for c in cols:
                v = it["metrics"].get(c)
                cells.append(_fmt_rate(v, c) if NON_ADDITIVE_RE.search(c) else _n(v))
            if not res["time_series"]:
                cells.append(_p(it.get("share")))
            if "Engagement" in head:
                cells.append(_p(it["derived"].get("engagement_rate")))
            out.append("| " + " | ".join(cells) + " |")
        if res["time_series"] and res["sorted_by"] and res["items"]:
            best = max(res["items"], key=lambda it: it["metrics"].get(res["sorted_by"]) or 0)
            worst = min(res["items"], key=lambda it: it["metrics"].get(res["sorted_by"]) or 0)
            out += ["", f"Highest {res['sorted_by']}: {best['dimension']}; lowest: {worst['dimension']}."]
        out.append("")
    return "\n".join(out)


def _pick_columns(metrics: list[str], limit: int = 7) -> list[str]:
    """Most useful metric columns first: known additive metrics, then rates, then the rest."""
    order = list(METRICS)

    def rank(c: str):
        key = canonical(c)
        if key:
            return (0, order.index(key))
        if re.search(r"rate", c, re.I):
            return (1, 0)
        return (2, 0)

    chosen = sorted(metrics, key=rank)[:limit]
    return [c for c in metrics if c in chosen]


def _fmt_rate(v, col: str) -> str:
    if v is None:
        return "-"
    if re.search(r"rate|%", col, re.I) and v <= 1:
        return _p(v)
    return f"{v:,.2f}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Summarise a GA4 report CSV or BigQuery export JSON (offline).")
    p.add_argument("path", help="GA4 CSV download, or BigQuery events as NDJSON / JSON array; - for stdin")
    p.add_argument("--top", type=int, default=10, help="rows per breakdown (default 10)")
    p.add_argument(
        "--conversion-events",
        default="purchase",
        help="BigQuery: comma-separated event names that count as conversions (default purchase)",
    )
    p.add_argument("--keep-query", action="store_true", help="BigQuery: keep ?query strings in landing pages")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        if args.path == "-":
            text = sys.stdin.read()
        else:
            with open(args.path, encoding="utf-8-sig") as fh:
                text = fh.read()
        stripped = text.lstrip("\ufeff").lstrip()
        if args.path.lower().endswith((".json", ".jsonl", ".ndjson")) or stripped.startswith(("{", "[")):
            conv = [c.strip() for c in args.conversion_events.split(",") if c.strip()]
            res = summarise_events(iter_events(text), conv, args.keep_query, args.top)
            if not res["totals"]["events"]:
                raise ValueError("no events found")
            output = json.dumps({"source": "bigquery", **res}, indent=2) if args.json else render_events(res)
        else:
            meta, tables = parse_ga4_csv(text)
            if not tables:
                raise ValueError("no data tables found in the CSV")
            results = [summarise_table(t, args.top) for t in tables]
            output = (
                json.dumps({"source": "csv", "meta": meta, "tables": results}, indent=2, ensure_ascii=False)
                if args.json
                else render_tables(meta, results)
            )
    except (OSError, UnicodeDecodeError, ValueError, AttributeError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(output if output.endswith("\n") else output + "\n", end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
