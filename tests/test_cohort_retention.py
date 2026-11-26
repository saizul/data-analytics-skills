import json
from datetime import date

import pytest

from conftest import FIXTURES, load_script, run_script, write_csv

SKILL = "cohort-retention"
SCRIPT = "cohort_retention.py"
mod = load_script(SKILL, SCRIPT)
LINES = FIXTURES / "orders_lines.csv"


def fixture_events(value_col=None):
    header, rows, _ = mod.read_table(str(LINES))
    return mod.load_events(header, rows, "customer_id", "order_date", "status", value_col)


def test_load_events_skips():
    events, skipped = fixture_events()
    assert skipped == {"no_user": 1, "bad_date": 0, "excluded_status": 2, "bad_value": 0}
    assert len(events) == 8


def test_monthly_table():
    events, _ = fixture_events()
    res = mod.cohorts(events, "month")
    assert res["users"] == 4 and res["last_period_complete"] is False
    rows = {r["cohort"]: r for r in res["cohorts"]}
    assert rows["2026-01"]["size"] == 2
    assert rows["2026-01"]["retention"] == [1.0, 0.5, 0.0]
    assert rows["2026-01"]["last_cell_partial"] is True
    assert rows["2026-02"]["retention"] == [1.0, 1.0]
    assert rows["2026-03"]["retention"] == [1.0]
    # partial cells are excluded from the weighted average
    assert res["weighted_average"] == [1.0, 0.5, None]


def test_value_per_user():
    events, _ = fixture_events("unit_price")
    res = mod.cohorts(events, "month")
    jan = res["cohorts"][0]
    assert jan["value_per_user"] == [pytest.approx(3700), pytest.approx(4950), pytest.approx(4950)]


def test_weekly_periods_start_monday():
    assert mod.period_start(mod.period_index(date(2026, 1, 7), "week"), "week") == date(2026, 1, 5)
    assert mod.period_start(mod.period_index(date(2026, 1, 5), "week"), "week") == date(2026, 1, 5)
    assert mod.period_index(date(2026, 2, 1), "month") - mod.period_index(date(2025, 12, 31), "month") == 2
    events, _ = fixture_events()
    res = mod.cohorts(events, "week", max_periods=4)
    assert res["cohorts"][0]["cohort"] == "2025-12-29"
    assert all(len(r["retention"]) <= 5 for r in res["cohorts"])


def test_complete_last_period_and_min_size(tmp_path):
    f = write_csv(
        tmp_path,
        "user_id,date\nu1,2026-01-01\nu2,2026-01-02\nu1,2026-02-03\nu3,2026-02-04\nu3,2026-03-31\nu2,2026-03-01\n",
    )
    header, rows, _ = mod.read_table(str(f))
    events, _ = mod.load_events(header, rows, "user_id", "date")
    res = mod.cohorts(events)
    assert res["last_period_complete"] is True
    rows_ = {r["cohort"]: r for r in res["cohorts"]}
    assert rows_["2026-01"]["retention"] == [1.0, 0.5, 0.5]
    assert rows_["2026-02"]["retention"] == [1.0, 1.0]
    assert res["weighted_average"] == [1.0, pytest.approx(2 / 3), 0.5]
    assert [r["cohort"] for r in mod.cohorts(events, min_size=2)["cohorts"]] == ["2026-01"]


def test_email_ids_are_case_insensitive(tmp_path):
    f = write_csv(tmp_path, "email,created_at\nA@x.example,2026-01-01\na@x.example,2026-02-01\n")
    header, rows, _ = mod.read_table(str(f))
    events, _ = mod.load_events(header, rows, "email", "created_at")
    assert mod.cohorts(events)["cohorts"][0]["retention"] == [1.0, 1.0]


def test_pick_columns():
    assert mod.pick(["Customer ID", "Order Date"], None, mod.USER_COLS, "user") == "Customer ID"
    with pytest.raises(ValueError, match="no user column"):
        mod.pick(["x"], None, mod.USER_COLS, "user")
    with pytest.raises(ValueError, match="not found"):
        mod.pick(["x"], "y", mod.USER_COLS, "user")
    with pytest.raises(ValueError, match="no usable rows"):
        mod.cohorts([])


def test_cli_outputs(tmp_path):
    r = run_script(SKILL, SCRIPT, str(LINES))
    assert r.returncode == 0
    assert "| 2026-01 | 2 | 100% | 50% | 0%* |" in r.stdout
    assert "| **Weighted avg** | | 100% | 50% | - |" in r.stdout
    r = run_script(SKILL, SCRIPT, str(LINES), "--value-col", "unit_price", "--currency", "BDT")
    assert "## Cumulative revenue per user (BDT)" in r.stdout
    r = run_script(SKILL, SCRIPT, str(LINES), "--format", "csv")
    assert r.stdout.splitlines()[0] == "cohort,users,period_0,period_1,period_2"
    r = run_script(SKILL, SCRIPT, str(LINES), "--json")
    data = json.loads(r.stdout)
    assert data["columns"]["status"] == "status" and data["skipped"]["no_user"] == 1
    assert run_script(SKILL, SCRIPT, str(LINES), "--user-col", "nope").returncode == 2
    assert run_script(SKILL, SCRIPT, str(tmp_path / "x.csv")).returncode == 2
