import json
from datetime import date

import pytest

from conftest import FIXTURES, load_script, run_script, write_csv

SKILL = "csv-profiling"
SCRIPT = "profile_csv.py"
mod = load_script(SKILL, SCRIPT)
MESSY = FIXTURES / "messy_orders.csv"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,250", 1250),
        ("1,00,000", 100000),
        ("12,34,567.50", 1234567.5),
        ("৳ ২,৫০০", 2500),
        ("Tk 900", 900),
        ("BDT 1,200", 1200),
        ("$12.50", 12.5),
        ("(300)", -300),
        ("-42", -42),
        ("1.5 lakh", 150000),
        ("2 crore", 20000000),
        ("১.৫ লাখ", 150000),
        ("3k", 3000),
        ("12.5%", 0.125),
        (".5", 0.5),
    ],
)
def test_parse_number(raw, expected):
    assert mod.parse_number(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["abc", "1,2345", "12,34,5678", "", "1.2.3", "2026-01-05", "lakh"])
def test_parse_number_rejects(raw):
    assert mod.parse_number(raw) is None


def test_parse_number_decimal_comma():
    assert mod.parse_number("1.234,56", decimal_comma=True) == pytest.approx(1234.56)


@pytest.mark.parametrize(
    "raw,order,expected,ambiguous",
    [
        ("2026-01-05", "dmy", "2026-01-05", False),
        ("05/01/2026", "dmy", "2026-01-05", True),
        ("05/01/2026", "mdy", "2026-05-01", True),
        ("13/01/2026", "mdy", "2026-01-13", False),
        ("01/13/2026", "dmy", "2026-01-13", False),
        ("12 Jan 2026", "dmy", "2026-01-12", False),
        ("Jan 12, 2026", "dmy", "2026-01-12", False),
        ("20260112", "dmy", "2026-01-12", False),
        ("০৫/০১/২০২৬", "dmy", "2026-01-05", True),
        ("5-1-26", "dmy", "2026-01-05", True),
    ],
)
def test_parse_date(raw, order, expected, ambiguous):
    dt, _, amb = mod.parse_date(raw, order)
    assert dt.date().isoformat() == expected and amb == ambiguous


def test_parse_date_times_and_invalid():
    dt, has_time, _ = mod.parse_date("2026-01-12T10:30:00Z")
    assert has_time and dt.hour == 10
    dt, has_time, _ = mod.parse_date("12/01/2026 2:30 PM")
    assert has_time and dt.hour == 14
    assert mod.parse_date("31/02/2026") is None
    assert mod.parse_date("hello") is None
    assert mod.parse_date("19000101x") is None


def test_profile_messy_fixture():
    header, rows, delim = mod.read_table(str(MESSY))
    assert delim == "," and len(rows) == 11
    res = mod.profile(header, rows, today=date(2026, 11, 26))
    cols = {c["name"]: c for c in res["fields"]}
    assert cols["Order ID"]["type"] == "integer"
    assert cols["Order Date"]["type"] == "date"
    assert cols["Order Date"]["dates"]["min"] == "2026-01-05"
    assert cols["Order Date"]["dates"]["max"] == "2026-01-14"
    assert cols["Phone"]["type"] == "code"
    assert cols["Amount"]["type"] == "number"
    assert cols["Amount"]["stats"]["max"] == 150000
    assert cols["Amount"]["stats"]["min"] == -300
    assert cols["Status"]["nulls"] == 1
    assert cols["City"]["name"] == "City"
    assert res["duplicate_rows"] == 1
    messages = [(i["column"], i["message"]) for i in res["issues"]]
    assert any(c == "Amount" and "not numeric" in m for c, m in messages)
    assert any(c == "Amount" and "outlier" in m for c, m in messages)
    assert any(c == "City" and "differ only by case" in m for c, m in messages)
    assert any(c == "Order Date" and "ambiguous" in m for c, m in messages)
    assert any(c == "Customer" and "spaces" in m for c, m in messages)
    assert any(c is None and "duplicate row" in m for c, m in messages)


def test_ragged_and_duplicate_headers(tmp_path):
    f = write_csv(tmp_path, "a,b,a\n1,2,3\n4,5\n6,7,8\n")
    header, rows, _ = mod.read_table(str(f))
    res = mod.profile(header, rows)
    high = [i["message"] for i in res["issues"] if i["severity"] == "high"]
    assert any("different number of fields" in m and "line 3" in m for m in high)
    assert any("duplicate column names" in m for m in high)


def test_clean_file_has_no_medium_issues(tmp_path):
    f = write_csv(tmp_path, "id,date,amount\n1,2026-01-01,10\n2,2026-01-02,12\n3,2026-01-03,11\n")
    header, rows, _ = mod.read_table(str(f))
    res = mod.profile(header, rows, today=date(2026, 2, 1))
    assert [i for i in res["issues"] if i["severity"] != "low"] == []
    assert res["fields"][0]["candidate_key"] is True


def test_future_dates_and_missing_days(tmp_path):
    f = write_csv(tmp_path, "day,v\n2026-01-01,1\n2026-01-04,2\n2027-01-01,3\n")
    header, rows, _ = mod.read_table(str(f))
    res = mod.profile(header, rows, today=date(2026, 6, 1))
    d = res["fields"][0]["dates"]
    assert d["future"] == 1 and d["missing_days"] == d["span_days"] - 3


def test_empty_and_constant_columns(tmp_path):
    f = write_csv(tmp_path, "a,b,c\n1,x,\n2,x,\n3,x,N/A\n")
    header, rows, _ = mod.read_table(str(f))
    res = mod.profile(header, rows)
    cols = {c["name"]: c for c in res["fields"]}
    assert cols["c"]["type"] == "empty"
    assert any(i["column"] == "b" and "constant" in i["message"] for i in res["issues"])


def test_semicolon_delimiter(tmp_path):
    f = write_csv(tmp_path, "a;b\n1;2\n3;4\n")
    header, rows, delim = mod.read_table(str(f))
    assert delim == ";" and header == ["a", "b"]


def test_cli_markdown_and_json():
    r = run_script(SKILL, SCRIPT, str(MESSY), "--today", "2026-11-26")
    assert r.returncode == 0
    assert "# Profile:" in r.stdout and "| Amount | number |" in r.stdout
    r = run_script(SKILL, SCRIPT, str(MESSY), "--json", "--today", "2026-11-26")
    data = json.loads(r.stdout)
    assert data["rows"] == 11 and data["columns"] == 7


def test_cli_fail_on_and_errors(tmp_path):
    assert run_script(SKILL, SCRIPT, str(MESSY), "--fail-on", "medium").returncode == 1
    assert run_script(SKILL, SCRIPT, str(MESSY), "--fail-on", "high").returncode == 0
    assert run_script(SKILL, SCRIPT, str(tmp_path / "missing.csv")).returncode == 2
    empty = write_csv(tmp_path, "")
    assert run_script(SKILL, SCRIPT, str(empty)).returncode == 2
    r = run_script(SKILL, SCRIPT, "-", stdin="a,b\n1,2\n")
    assert r.returncode == 0 and "Rows: 1" in r.stdout


def test_skips_comment_header(tmp_path):
    f = write_csv(tmp_path, "# exported report\n# Start date: 20261001\nDate,Sessions\n20261001,5\n")
    header, rows, _ = mod.read_table(str(f))
    assert header == ["Date", "Sessions"] and rows == [["20261001", "5"]]


def test_redact_hides_text_values():
    header, rows, _ = mod.read_table(str(MESSY))
    res = mod.profile(header, rows, redact=True)
    cols = {c["name"]: c for c in res["fields"]}
    assert cols["Customer"]["top"] == [] and cols["Phone"]["top"] == []
    assert cols["Amount"]["top"]
    text = json.dumps(res, ensure_ascii=False)
    assert "Rahim" not in text and "01711000001" not in text
    assert 'e.g. "abc"' not in text
    r = run_script(SKILL, SCRIPT, str(MESSY), "--redact")
    assert r.returncode == 0 and "Rahim" not in r.stdout and "DHAKA" not in r.stdout
