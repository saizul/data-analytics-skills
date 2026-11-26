import json

import pytest

from conftest import FIXTURES, load_script, run_script, write_csv

SKILL = "ga4-export-analysis"
SCRIPT = "ga4_summary.py"
mod = load_script(SKILL, SCRIPT)
GA4 = FIXTURES / "ga4"


def tables(name):
    return mod.parse_ga4_csv((GA4 / name).read_text(encoding="utf-8"))


def test_parse_meta_and_tables():
    meta, ts = tables("traffic_acquisition.csv")
    assert meta["start"] == "2026-10-01" and meta["end"] == "2026-10-31"
    assert meta["title"].startswith("Traffic acquisition")
    assert len(ts) == 2 and ts[0]["header"][0] == "Session source / medium" and len(ts[0]["rows"]) == 5


def test_traffic_table_totals_and_rates():
    _, ts = tables("traffic_acquisition.csv")
    res = mod.summarise_table(ts[0])
    assert res["dimensions"] == ["Session source / medium"]
    assert res["totals"]["Sessions"] == 9000
    assert res["totals"]["Engaged sessions"] == 5460
    assert res["totals"]["Key events"] == 240
    assert res["totals"]["Total revenue"] == 554000
    assert "Engagement rate" not in res["totals"] and "Engagement rate" in res["non_additive"]
    assert res["derived"]["engagement_rate"] == pytest.approx(5460 / 9000)
    assert res["derived"]["key_events_per_session"] == pytest.approx(240 / 9000)
    assert res["items"][0]["dimension"] == "google / organic"
    assert res["items"][0]["share"] == pytest.approx(4200 / 9000)


def test_date_table_is_sorted_time_series():
    _, ts = tables("traffic_acquisition.csv")
    res = mod.summarise_table(ts[1])
    assert res["time_series"] is True
    assert [i["dimension"] for i in res["items"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert res["totals"]["Sessions"] == 930


def test_landing_pages_skip_grand_total_and_users():
    _, ts = tables("landing_pages.csv")
    res = mod.summarise_table(ts[0], top=2)
    assert res["rows"] == 4
    assert res["totals"]["Sessions"] == 5800
    assert "Total users" not in res["totals"]
    assert len(res["items"]) == 2 and res["items"][1]["dimension"] == "/products/cotton-saree"
    assert res["items"][0]["metrics"]["Engagement rate"] == pytest.approx(0.652)


def test_bigquery_events():
    text = (GA4 / "bigquery_events.ndjson").read_text()
    res = mod.summarise_events(mod.iter_events(text), ["purchase", "generate_lead"])
    t = res["totals"]
    assert t["users"] == 3 and t["sessions"] == 4
    assert t["engaged_sessions"] == 3 and t["page_views"] == 4
    assert t["conversions"] == 3 and t["converting_sessions"] == 3
    assert t["revenue"] == pytest.approx(4300)
    assert t["events_without_session"] == 1
    src = {g["key"]: g for g in res["by_source_medium"]}
    assert set(src) == {"facebook / paid", "google / organic", "newsletter / email", "(direct) / (none)"}
    assert src["facebook / paid"]["revenue"] == 2500 and src["newsletter / email"]["revenue"] == 1800
    pages = {g["key"]: g for g in res["by_landing_page"]}
    assert pages["/"]["sessions"] == 2 and "/products/saree" in pages
    assert [d["key"] for d in res["by_date"]] == ["2026-10-01", "2026-10-02"]
    assert res["from"] == "2026-10-01" and res["to"] == "2026-10-02"


def test_bigquery_default_conversion_and_keep_query():
    text = (GA4 / "bigquery_events.ndjson").read_text()
    res = mod.summarise_events(mod.iter_events(text), keep_query=True)
    assert res["totals"]["conversions"] == 2
    assert any("?utm_source=facebook" in g["key"] for g in res["by_landing_page"])


def test_json_array_and_gclid(tmp_path):
    events = [
        {
            "event_date": "20261005",
            "event_timestamp": "1",
            "event_name": "page_view",
            "user_pseudo_id": "u",
            "event_params": [
                {"key": "ga_session_id", "value": {"int_value": "9"}},
                {"key": "page_location", "value": {"string_value": "https://x.example/a"}},
            ],
            "collected_traffic_source": {"gclid": "abc"},
        },
    ]
    res = mod.summarise_events(mod.iter_events(json.dumps(events)))
    assert res["by_source_medium"][0]["key"] == "google / cpc"
    with pytest.raises(ValueError, match="line 2"):
        list(mod.iter_events('{"a": 1}\n{broken\n'))


def test_num_and_canonical():
    assert mod.num("1,234") == 1234 and mod.num("61.2%") == pytest.approx(0.612) and mod.num("abc") is None
    assert mod.canonical("Key events (purchase)") == "key_events"
    assert mod.canonical("Total revenue (USD)") == "revenue"
    assert mod.canonical("Bounce rate") is None


def test_cli(tmp_path):
    r = run_script(SKILL, SCRIPT, str(GA4 / "traffic_acquisition.csv"))
    assert r.returncode == 0 and "# GA4 report summary: 2026-10-01 to 2026-10-31" in r.stdout
    assert "- Total sessions: 9,000" in r.stdout and "| google / organic | 4,200 |" in r.stdout
    r = run_script(SKILL, SCRIPT, str(GA4 / "bigquery_events.ndjson"), "--conversion-events", "purchase,generate_lead")
    assert r.returncode == 0 and "| Sessions | 4 |" in r.stdout and "## Top landing page" in r.stdout
    r = run_script(SKILL, SCRIPT, str(GA4 / "landing_pages.csv"), "--json")
    assert json.loads(r.stdout)["tables"][0]["totals"]["Sessions"] == 5800
    r = run_script(SKILL, SCRIPT, str(GA4 / "bigquery_events.ndjson"), "--json")
    assert json.loads(r.stdout)["source"] == "bigquery"
    empty = write_csv(tmp_path, "# only comments\n", "empty.csv")
    assert run_script(SKILL, SCRIPT, str(empty)).returncode == 2
    bad = write_csv(tmp_path, "{not json\n", "bad.json")
    assert run_script(SKILL, SCRIPT, str(bad)).returncode == 2
    assert run_script(SKILL, SCRIPT, str(tmp_path / "missing.csv")).returncode == 2
