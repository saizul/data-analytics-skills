import csv
import json

from conftest import FIXTURES, load_script, run_script, write_csv

SKILL = "data-cleaning"
SCRIPT = "clean_csv.py"
mod = load_script(SKILL, SCRIPT)
MESSY = FIXTURES / "messy_orders.csv"


def clean_fixture(**kw):
    header, rows, _ = mod.read_table(str(MESSY))
    return mod.clean(header, rows, **kw)


def test_auto_detects_columns_and_normalises():
    header, rows, report = clean_fixture(case={"City": "title"})
    assert report["number_columns"] == ["Order ID", "Amount"]
    assert report["date_columns"] == ["Order Date"]
    by_id = {r[0]: dict(zip(header, r)) for r in rows}
    assert by_id["1001"]["Amount"] == "1250"
    assert by_id["1002"]["Amount"] == "2500"
    assert by_id["1003"]["Amount"] == "100000"
    assert by_id["1004"]["Amount"] == "900"
    assert by_id["1006"]["Amount"] == "150000"
    assert by_id["1009"]["Amount"] == "-300"
    assert by_id["1005"]["Amount"] == "abc"
    assert by_id["1001"]["Order Date"] == "2026-01-05"
    assert by_id["1004"]["Order Date"] == "2026-01-08"
    assert by_id["1002"]["City"] == "Dhaka" and by_id["1010"]["City"] == "Dhaka"
    assert by_id["1005"]["Customer"] == "Sadia Khan"
    assert by_id["1010"]["Status"] == ""
    assert by_id["1001"]["Phone"] == "01711000001"
    assert len(rows) == 10
    assert report["duplicates_removed"] == [{"line": 7, "duplicate_of": 6}]
    assert report["unparseable"]["Amount"][0] == {"line": 6, "value": "abc"}
    assert report["ambiguous_dates"] == 8
    assert report["nulls_blanked"] == 1


def test_mdy_order():
    header, rows, _ = clean_fixture(order="mdy")
    by_id = {r[0]: dict(zip(header, r)) for r in rows}
    assert by_id["1001"]["Order Date"] == "2026-05-01"
    assert by_id["1003"]["Order Date"] == "2026-07-01"


def test_key_dedupe_keep_last(tmp_path):
    f = write_csv(tmp_path, "id,status\n1,pending\n2,paid\n1,paid\n,x\n,x\n")
    header, rows, _ = mod.read_table(str(f))
    _, out, report = mod.clean(header, rows, dedupe="key", keys=["id"], keep="last")
    assert out == [["2", "paid"], ["1", "paid"], ["", "x"], ["", "x"]]
    assert report["duplicates_removed"] == [{"line": 2, "duplicate_of": 4}]


def test_dedupe_after_normalisation(tmp_path):
    f = write_csv(tmp_path, 'id,amount\n1,"1,250"\n1,1250\n1, 1250 \n')
    header, rows, _ = mod.read_table(str(f))
    _, out, report = mod.clean(header, rows)
    assert out == [["1", "1250"]] and len(report["duplicates_removed"]) == 2


def test_no_dedupe_and_snake_headers(tmp_path):
    f = write_csv(tmp_path, "Order ID, Unit Price (BDT) \n1,10\n1,10\n")
    header, rows, _ = mod.read_table(str(f))
    new_header, out, report = mod.clean(header, rows, dedupe="none", snake_headers=True)
    assert new_header == ["order_id", "unit_price_bdt"] and len(out) == 2
    assert report["renamed"]["Order ID"] == "order_id"


def test_ascii_digits_and_codes(tmp_path):
    f = write_csv(tmp_path, "phone,note\n০১৭১১০০০০০১,বাড়ি ১২\n")
    header, rows, _ = mod.read_table(str(f))
    _, out, _ = mod.clean(header, rows)
    assert out[0] == ["০১৭১১০০০০০১", "বাড়ি ১২"]
    _, out, report = mod.clean(header, rows, ascii_digits=True)
    assert out[0][0] == "01711000001" and report["digits_converted"] == 2


def test_decimal_comma_and_explicit_columns(tmp_path):
    f = write_csv(tmp_path, "amount;when\n1.234,56;12 Jan 2026\n")
    header, rows, _ = mod.read_table(str(f))
    _, out, _ = mod.clean(header, rows, number_cols=["amount"], date_cols=["when"], decimal_comma=True)
    assert out == [["1234.56", "2026-01-12"]]


def test_unknown_column_raises(tmp_path):
    f = write_csv(tmp_path, "a\n1\n")
    header, rows, _ = mod.read_table(str(f))
    try:
        mod.clean(header, rows, number_cols=["nope"])
    except ValueError as exc:
        assert "unknown column" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_ragged_rows_are_padded_and_reported(tmp_path):
    f = write_csv(tmp_path, "a,b,c\n1,2\n")
    header, rows, _ = mod.read_table(str(f))
    _, out, report = mod.clean(header, rows)
    assert out == [["1", "2", ""]] and report["ragged_rows"] == [2]


def test_cli_dry_run_writes_nothing(tmp_path):
    r = run_script(SKILL, SCRIPT, str(MESSY))
    assert r.returncode == 0 and "Dry run" in r.stdout
    assert list(tmp_path.iterdir()) == []


def test_cli_writes_output(tmp_path):
    out = tmp_path / "clean.csv"
    r = run_script(SKILL, SCRIPT, str(MESSY), "--out", str(out), "--case", "City=title", "--excel-bom")
    assert r.returncode == 0 and f"Wrote {out}" in r.stdout
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(out.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0][0] == "Order ID" and len(rows) == 11


def test_cli_json_strict_and_errors(tmp_path):
    r = run_script(SKILL, SCRIPT, str(MESSY), "--json", "--strict")
    assert r.returncode == 1
    data = json.loads(r.stdout)
    assert data["rows_in"] == 11 and data["rows_out"] == 10
    assert run_script(SKILL, SCRIPT, str(MESSY), "--out", str(MESSY)).returncode == 2
    assert run_script(SKILL, SCRIPT, str(MESSY), "--dedupe", "key").returncode == 2
    assert run_script(SKILL, SCRIPT, str(MESSY), "--case", "City=camel").returncode == 2
    assert run_script(SKILL, SCRIPT, str(tmp_path / "nope.csv")).returncode == 2
    good = write_csv(tmp_path, "a,b\n1,2\n")
    assert run_script(SKILL, SCRIPT, str(good), "--strict").returncode == 0
