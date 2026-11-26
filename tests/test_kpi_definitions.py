import json

import pytest

from conftest import FIXTURES, ROOT, load_script, run_script, write_csv

SKILL = "kpi-definitions"
SCRIPT = "validate_kpis.py"
mod = load_script(SKILL, SCRIPT)
EXAMPLE = ROOT / "skills" / SKILL / "assets" / "kpis.example.yaml"
BAD = FIXTURES / "kpis" / "bad.yaml"


def messages(result, level="errors"):
    return [f"{i['where']}: {i['message']}" for i in result[level]]


def test_asset_matches_template_and_is_valid():
    assert EXAMPLE.read_text(encoding="utf-8") == mod.TEMPLATE
    result = mod.validate(mod.load(str(EXAMPLE)))
    assert result["errors"] == [] and result["warnings"] == []
    assert result["kpis"] == ["net_revenue", "aov", "repeat_rate"]


def test_bad_fixture_errors():
    result = mod.validate(mod.load(str(BAD)))
    errs = messages(result)
    assert any("input sessions" in e and "aggregation 'total'" in e for e in errs)
    assert any("kpi aov" in e and "placeholder" in e for e in errs)
    assert any("ConversionRate" in e and "snake_case" in e for e in errs)
    assert any("ConversionRate" in e and "grain 'weekly'" in e for e in errs)
    assert any("ConversionRate" in e and "unknown name 'visits'" in e for e in errs)
    assert any("loop_b" in e and "does not parse" in e for e in errs)
    assert any("loop_b" in e and "direction 'sideways'" in e for e in errs)
    assert any("margin" in e and "median_of()" in e for e in errs)
    assert any("circular definition: loop_a -> loop_b -> loop_a" in e for e in errs)
    warns = messages(result, "warnings")
    assert any("kpi aov" in w and "zero_division" in w for w in warns)
    assert any("kpi aov" in w and "currency code" in w for w in warns)
    assert any("kpi aov" in w and "add direction" in w for w in warns)
    assert any("input orders" in w and "description" in w for w in warns)
    assert any("input sessions" in w and "not used" in w for w in warns)
    assert any("margin" in w and "no division" in w for w in warns)


@pytest.mark.parametrize(
    "formula,idents,funcs,div,error",
    [
        ("revenue / orders", {"revenue", "orders"}, set(), True, None),
        ("(a - b) * 100 / nullif(c, 0)", {"a", "b", "c"}, {"nullif"}, True, None),
        ("-a + round(b, 2)", {"a", "b"}, {"round"}, False, None),
        ("a +", {"a"}, set(), False, "unexpected 'end of formula'"),
        ("a $ b", set(), set(), False, "unexpected character '$'"),
        ("sum(a", {"a"}, {"sum"}, False, "missing ')' after sum("),
        ("", set(), set(), False, "formula is empty"),
        ("a b", {"a"}, set(), False, "unexpected 'b'"),
    ],
)
def test_parse_formula(formula, idents, funcs, div, error):
    got = mod.parse_formula(formula)
    assert got[0] == idents and got[1] == funcs and got[2] == div and got[3] == error


def test_yaml_subset_parser():
    text = """
# comment
version: 1
title: "Quoted: value"   # trailing comment
tags: [sales, monthly]
nested:
  a: 1
  b: 2.5
  c: true
  d: null
note: >
  folded
  text
list:
- one
- 'two # not a comment'
items:
  - id: x
    sub:
      k: v
  -
    id: y
"""
    data = mod.parse_yaml(text)
    assert data["version"] == 1
    assert data["title"] == "Quoted: value"
    assert data["tags"] == ["sales", "monthly"]
    assert data["nested"] == {"a": 1, "b": 2.5, "c": True, "d": None}
    assert data["note"] == "folded text"
    assert data["list"] == ["one", "two # not a comment"]
    assert data["items"] == [{"id": "x", "sub": {"k": "v"}}, {"id": "y"}]


@pytest.mark.parametrize(
    "text,message",
    [
        ("a: 1\n\tb: 2\n", "tabs"),
        ("a: 1\na: 2\n", "duplicate key"),
        ("a: 1\n    b: 2\n", "unexpected indentation"),
        ("just text\n", "expected 'key: value'"),
    ],
)
def test_yaml_errors(text, message):
    with pytest.raises(mod.YamlError, match=message):
        mod.parse_yaml(text)


def test_json_input_and_list_form(tmp_path):
    doc = [
        {
            "id": "orders_count",
            "name": "Orders",
            "description": "Distinct paid orders in the period",
            "formula": "count_distinct(order_id)",
            "unit": "count",
            "grain": "day",
            "owner": "Ops",
            "direction": "up",
        }
    ]
    f = tmp_path / "kpis.json"
    f.write_text(json.dumps(doc))
    result = mod.validate(mod.load(str(f)))
    assert any("unknown name 'order_id'" in m for m in messages(result))


def test_coarser_grain_warning():
    doc = {
        "inputs": [
            {"id": "rev", "description": "Revenue of paid orders", "source": "orders.csv", "aggregation": "sum"}
        ],
        "kpis": [
            {
                "id": "monthly_rev",
                "name": "M",
                "description": "Revenue per month total",
                "formula": "rev",
                "unit": "count",
                "grain": "month",
                "owner": "Fin",
                "direction": "up",
            },
            {
                "id": "daily_share",
                "name": "D",
                "description": "Daily share of the monthly revenue",
                "formula": "rev / monthly_rev",
                "unit": "ratio",
                "grain": "day",
                "owner": "Fin",
                "direction": "up",
                "zero_division": None,
            },
        ],
    }
    result = mod.validate(doc)
    assert result["errors"] == []
    assert any("coarser grain" in w for w in messages(result, "warnings"))


def test_structure_errors():
    assert messages(mod.validate("text"))[0].startswith("file: expected")
    assert any("non-empty list" in m for m in messages(mod.validate({"kpis": []})))
    assert any("missing 'owner'" in m for m in messages(mod.validate({"kpis": [{"id": "a", "formula": "1"}]})))
    assert any("duplicate id" in m for m in messages(mod.validate({"kpis": [{"id": "a"}, {"id": "a"}]})))


def test_markdown_rendering():
    md = mod.render_markdown(mod.load(str(EXAMPLE)))
    assert md.startswith("# Metric dictionary")
    assert "| **Average order value** (`aov`) |" in md and "currency (BDT)" in md
    assert "## Inputs" in md and "`gross_revenue`" in md


def test_cli(tmp_path):
    r = run_script(SKILL, SCRIPT, str(EXAMPLE), "--markdown")
    assert r.returncode == 0 and "0 error(s), 0 warning(s)" in r.stdout and "# Metric dictionary" in r.stdout
    r = run_script(SKILL, SCRIPT, str(BAD))
    assert r.returncode == 1 and "## Errors" in r.stdout
    r = run_script(SKILL, SCRIPT, str(BAD), "--json")
    assert r.returncode == 1 and len(json.loads(r.stdout)["errors"]) == 9
    r = run_script(SKILL, SCRIPT, "--template")
    assert r.returncode == 0 and r.stdout == mod.TEMPLATE
    warn_only = tmp_path / "w.yaml"
    warn_only.write_text(mod.TEMPLATE.replace("    direction: up\n    zero_division: null\n", "    direction: up\n"))
    assert run_script(SKILL, SCRIPT, str(warn_only)).returncode == 0
    assert run_script(SKILL, SCRIPT, str(warn_only), "--strict").returncode == 1
    broken = write_csv(tmp_path, "a: 1\n\tb: 2\n", "broken.yaml")
    assert run_script(SKILL, SCRIPT, str(broken)).returncode == 2
    assert run_script(SKILL, SCRIPT, str(tmp_path / "missing.yaml")).returncode == 2
    assert run_script(SKILL, SCRIPT).returncode == 2
