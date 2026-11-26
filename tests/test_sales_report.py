import json
from datetime import date

import pytest

from conftest import FIXTURES, load_script, run_script, write_csv

SKILL = "sales-report"
SCRIPT = "sales_report.py"
mod = load_script(SKILL, SCRIPT)
LINES = FIXTURES / "orders_lines.csv"


def build(path=LINES, period="month", **kw):
    header, rows, _ = mod.read_table(str(path))
    cols = mod.detect(header, kw.pop("overrides", {}))
    orders, skipped, _ = mod.build_orders(header, rows, cols, **kw)
    return mod.report(orders, period), skipped, cols


def test_line_item_fixture_summary():
    r, skipped, cols = build()
    assert cols["price"] == "unit_price" and cols["amount"] is None
    s = r["summary"]
    assert s["revenue"] == 21500 and s["orders"] == 8
    assert s["aov"] == pytest.approx(2687.5)
    assert s["units"] == 14
    assert s["customers"] == 4 and s["repeat_customers"] == 3
    assert s["repeat_rate"] == pytest.approx(0.75)
    assert s["orders_without_customer"] == 1
    assert skipped["excluded_status"] == 2
    assert s["last_period_complete"] is False


def test_monthly_periods_new_vs_returning():
    r, _, _ = build()
    p = {x["period"]: x for x in r["periods"]}
    assert p["2026-01"]["revenue"] == 8000 and p["2026-01"]["orders"] == 3
    assert p["2026-02"]["revenue"] == 6800
    assert p["2026-02"]["new_customers"] == 1 and p["2026-02"]["returning_customers"] == 1
    assert p["2026-02"]["revenue_change"] == pytest.approx(-0.15)
    assert p["2026-03"]["revenue"] == 6700


def test_top_products():
    r, _, _ = build()
    top = r["top_products"]
    assert [t["product"] for t in top] == ["Cotton Saree", "Panjabi", "Silk Scarf"]
    assert top[0]["revenue"] == 12500 and top[0]["units"] == 5 and top[0]["orders"] == 4
    assert sum(t["share"] for t in top) == pytest.approx(1.0)


def test_weekly_and_daily_fill_gaps():
    r, _, _ = build(period="week")
    assert r["periods"][0]["period"].startswith("2025-W53") or r["periods"][0]["start"] == "2025-12-29"
    starts = [date.fromisoformat(p["start"]) for p in r["periods"]]
    assert all((b - a).days == 7 for a, b in zip(starts, starts[1:]))
    r, _, _ = build(period="day")
    assert len(r["periods"]) == (date(2026, 3, 9) - date(2026, 1, 3)).days + 1


def test_include_all_statuses_and_date_range():
    r, skipped, _ = build(exclude=set())
    assert r["summary"]["orders"] == 10 and skipped["excluded_status"] == 0
    r, skipped, _ = build(start=date(2026, 2, 1), end=date(2026, 2, 28))
    assert r["summary"]["orders"] == 2 and skipped["outside_range"] > 0


def test_order_level_amount_file(tmp_path):
    f = write_csv(
        tmp_path,
        "Order Number,Date,Customer Email,Total,Status\n"
        '1,05/01/2026,A@x.example,"1,00,000",completed\n'
        "2,06/01/2026,b@x.example,Tk 500,completed\n"
        "3,07/01/2026,a@x.example,(200),completed\n"
        "4,bad-date,a@x.example,10,completed\n"
        "5,08/01/2026,a@x.example,abc,completed\n",
    )
    r, skipped, cols = build(f)
    assert cols["amount"] == "Total" and cols["order"] == "Order Number"
    assert r["summary"]["revenue"] == 100300
    assert skipped["bad_date"] == 1 and skipped["bad_amount"] == 1
    assert r["summary"]["customers"] == 3  # emails differ in case; ids are kept as given


def test_shopify_style_status_on_first_line(tmp_path):
    f = write_csv(
        tmp_path,
        "Name,Created at,Email,Financial Status,Lineitem name,Lineitem quantity,Lineitem price,Total\n"
        "#1001,2026-01-01 10:00:00 +0600,a@x.example,paid,Saree,1,2500,3100\n"
        "#1001,2026-01-01 10:00:00 +0600,a@x.example,,Scarf,1,600,\n"
        "#1002,2026-01-02 11:00:00 +0600,b@x.example,refunded,Saree,1,2500,2500\n"
        "#1002,2026-01-02 11:00:00 +0600,b@x.example,,Scarf,2,600,\n",
    )
    r, skipped, cols = build(f)
    assert cols["price"] == "Lineitem price" and cols["amount"] is None
    assert r["summary"]["orders"] == 1 and r["summary"]["revenue"] == 3100
    assert skipped["excluded_status"] == 2


def test_amount_override(tmp_path):
    f = write_csv(tmp_path, "id,date,price,qty,net\n1,2026-01-01,10,2,15\n")
    r, _, cols = build(f, overrides={"amount": "net"})
    assert cols["price"] is None and r["summary"]["revenue"] == 15


def test_detect_errors():
    with pytest.raises(ValueError, match="no date column"):
        mod.detect(["id", "total"], {})
    with pytest.raises(ValueError, match="no amount"):
        mod.detect(["id", "date"], {})
    with pytest.raises(ValueError, match="not found"):
        mod.detect(["id", "date", "total"], {"amount": "nope"})


@pytest.mark.parametrize(
    "x,indian,expected",
    [
        (100000, True, "1,00,000"),
        (12345678, True, "1,23,45,678"),
        (999, True, "999"),
        (-150000, True, "-1,50,000"),
        (1234567, False, "1,234,567"),
        (None, False, "-"),
    ],
)
def test_money(x, indian, expected):
    assert mod.money(x, indian) == expected


def test_cli_markdown_json_and_errors(tmp_path):
    r = run_script(SKILL, SCRIPT, str(LINES), "--currency", "BDT", "--lakh")
    assert r.returncode == 0
    assert "| Revenue | BDT 21,500 |" in r.stdout and "## Top products" in r.stdout
    assert "Repeat customer rate | 75.0%" in r.stdout and "may be incomplete" in r.stdout
    assert "c1" not in r.stdout  # customer ids are never printed
    r = run_script(SKILL, SCRIPT, str(LINES), "--json", "--period", "week")
    data = json.loads(r.stdout)
    assert data["summary"]["orders"] == 8 and data["period"] == "week"
    r = run_script(SKILL, SCRIPT, str(LINES), "--exclude-status", "cancelled")
    assert "| Orders | 9 |" in r.stdout
    assert run_script(SKILL, SCRIPT, str(LINES), "--from", "2030-01-01").returncode == 2
    assert run_script(SKILL, SCRIPT, str(tmp_path / "none.csv")).returncode == 2
    no_amount = write_csv(tmp_path, "id,date\n1,2026-01-01\n")
    r = run_script(SKILL, SCRIPT, str(no_amount))
    assert r.returncode == 2 and "amount" in r.stderr
