import json
from datetime import date, timedelta

import pytest

from conftest import FIXTURES, load_script, run_script, write_csv

SKILL = "anomaly-alerts"
SCRIPT = "detect_anomalies.py"
mod = load_script(SKILL, SCRIPT)
DAILY = FIXTURES / "daily_metrics.csv"


def series():
    header, rows, _ = mod.read_table(str(DAILY))
    return mod.load_series(header, rows)


def test_load_series_detects_columns():
    date_col, s, bad = series()
    assert date_col == "date" and set(s) == {"revenue", "sessions"} and bad == 0
    assert len(s["revenue"]) == 34


def test_fixture_spike_drop_and_missing():
    _, s, _ = series()
    recs = mod.score(s["revenue"])
    found = {r["date"]: r for r in recs if r["anomaly"]}
    assert set(found) == {"2026-10-20", "2026-10-28", "2026-10-31"}
    assert found["2026-10-20"]["type"] == "spike" and found["2026-10-20"]["expected"] == 10000
    assert found["2026-10-28"]["type"] == "drop" and found["2026-10-28"]["change"] < -0.6
    assert found["2026-10-31"]["type"] == "missing"
    first = recs[0]
    assert "z" not in first  # not enough history yet
    sessions = [r for r in mod.score(s["sessions"]) if r["anomaly"]]
    assert [r["type"] for r in sessions] == ["missing"]


def test_direction_and_min_abs():
    _, s, _ = series()
    down = [r["date"] for r in mod.score(s["revenue"], direction="down") if r["anomaly"] and not r["missing"]]
    assert down == ["2026-10-28"]
    big = [r for r in mod.score(s["revenue"], min_abs=10000) if r["anomaly"] and not r["missing"]]
    assert [r["date"] for r in big] == ["2026-10-20"]


def test_flat_history_and_zero_median():
    d0 = date(2026, 1, 1)
    flat = {d0 + timedelta(days=i): 100.0 for i in range(10)}
    flat[d0 + timedelta(days=10)] = 150.0
    rec = mod.score(flat)[-1]
    assert rec["anomaly"] and rec["z"] == float("inf")
    zeros = {d0 + timedelta(days=i): 0.0 for i in range(10)}
    zeros[d0 + timedelta(days=10)] = 5.0
    rec = mod.score(zeros)[-1]
    assert rec["anomaly"] and rec["change"] is None


def test_weekly_seasonality_avoids_weekend_alerts():
    d0 = date(2026, 1, 5)  # Monday
    values = {}
    for i in range(70):
        d = d0 + timedelta(days=i)
        values[d] = (300.0 if d.weekday() >= 5 else 100.0) + (i % 3)
    plain = [r for r in mod.score(values) if r["anomaly"]]
    weekly = [r for r in mod.score(values, window=8, min_periods=4, seasonal="weekly") if r["anomaly"]]
    assert plain and not weekly


def test_duplicate_dates_are_summed(tmp_path):
    f = write_csv(tmp_path, 'order_date,amount\n05/01/2026,100\n05/01/2026,"1,200"\nbad,5\n')
    header, rows, _ = mod.read_table(str(f))
    _, s, bad = mod.load_series(header, rows, value_cols=["amount"])
    assert s["amount"] == {date(2026, 1, 5): 1300.0} and bad == 1


def test_load_series_errors(tmp_path):
    f = write_csv(tmp_path, "x,y\n1,2\n")
    header, rows, _ = mod.read_table(str(f))
    with pytest.raises(ValueError, match="no date column"):
        mod.load_series(header, rows)
    with pytest.raises(ValueError, match="not found"):
        mod.load_series(header, rows, date_col="x", value_cols=["nope"])
    f = write_csv(tmp_path, "date,name\n2026-01-01,a\n", "t.csv")
    header, rows, _ = mod.read_table(str(f))
    with pytest.raises(ValueError, match="no numeric"):
        mod.load_series(header, rows)


def test_alert_line():
    line = mod.alert_line(
        "revenue",
        {"date": "2026-10-28", "value": 3000, "expected": 10150, "change": -0.7044, "z": -12.1, "type": "drop"},
    )
    assert line == "2026-10-28 revenue: 3,000 is 70% below expected 10,150 (robust z -12.1)"
    assert "no data" in mod.alert_line("orders", {"date": "2026-10-31", "type": "missing"})


def test_cli():
    r = run_script(SKILL, SCRIPT, str(DAILY))
    assert r.returncode == 1 and "| 2026-10-20 | revenue | 25,000 | 10,000 | +150% |" in r.stdout
    r = run_script(SKILL, SCRIPT, str(DAILY), "--last", "3", "--value-col", "revenue")
    assert r.returncode == 0 and "No anomalies found." in r.stdout
    r = run_script(SKILL, SCRIPT, str(DAILY), "--format", "alert", "--ignore-missing")
    assert r.returncode == 1 and len(r.stdout.strip().splitlines()) == 2
    r = run_script(SKILL, SCRIPT, str(DAILY), "--json", "--value-col", "sessions")
    data = json.loads(r.stdout)
    assert [a["type"] for a in data["anomalies"]] == ["missing"]
    r = run_script(SKILL, SCRIPT, str(DAILY), "--seasonal", "weekly")
    assert "same weekday" in r.stdout
    assert run_script(SKILL, SCRIPT, str(DAILY), "--date-col", "nope").returncode == 2
