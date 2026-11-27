import json

import pytest

from conftest import FIXTURES, load_script, run_script, write_csv

SKILL = "ab-test-analysis"
SCRIPT = "ab_test.py"
mod = load_script(SKILL, SCRIPT)
AB = FIXTURES / "ab"


def test_z_test_known_values():
    t = mod.z_test(10000, 500, 10000, 580)
    assert t["z"] == pytest.approx(2.5032, abs=1e-3)
    assert t["p_value"] == pytest.approx(0.01231, abs=1e-4)
    assert mod.z_test(10000, 500, 10000, 580, "greater")["p_value"] == pytest.approx(t["p_value"] / 2)
    assert mod.z_test(10000, 500, 10000, 580, "less")["p_value"] == pytest.approx(1 - t["p_value"] / 2)
    assert mod.z_test(100, 0, 100, 0)["p_value"] == 1.0


def test_diff_ci():
    lo, hi = mod.diff_ci(10000, 500, 10000, 580)
    assert lo == pytest.approx(0.00173, abs=1e-4) and hi == pytest.approx(0.01427, abs=1e-4)


@pytest.mark.parametrize(
    "baseline,mde,relative,alpha,power,alt,expected",
    [
        (0.05, 0.10, True, 0.05, 0.8, "two-sided", 31234),
        (0.10, 0.02, False, 0.05, 0.8, "two-sided", 3841),
        (0.20, 0.25, True, 0.05, 0.9, "two-sided", 1464),
    ],
)
def test_sample_size(baseline, mde, relative, alpha, power, alt, expected):
    assert mod.sample_size(baseline, mde, relative, alpha, power, alt) == pytest.approx(expected, abs=2)


def test_sample_size_one_sided_is_smaller_and_invalid():
    assert mod.sample_size(0.05, 0.1, alternative="greater") < mod.sample_size(0.05, 0.1)
    with pytest.raises(ValueError):
        mod.sample_size(0.05, 0.0)
    with pytest.raises(ValueError):
        mod.sample_size(0.95, 0.1)


@pytest.mark.parametrize(
    "a,x,expected", [(0.5, 1.92, 0.05), (1.0, 2.996, 0.05), (1.5, 3.907, 0.05), (2.0, 0.5, 0.9098)]
)
def test_gammaincc_matches_chi_square_tables(a, x, expected):
    assert mod.gammaincc(a, x) == pytest.approx(expected, abs=2e-3)


def test_srm():
    assert mod.srm_check([10000, 10000])["p_value"] == pytest.approx(1.0)
    assert mod.srm_check([10000, 9000])["p_value"] < 1e-6
    assert mod.srm_check([9000, 1000], [90, 10])["p_value"] == pytest.approx(1.0)
    assert mod.srm_check([5000, 5100, 4900])["p_value"] > 0.05


def test_analyze_two_groups():
    res = mod.analyze(
        [{"name": "A", "visitors": 10000, "conversions": 500}, {"name": "B", "visitors": 10000, "conversions": 580}]
    )
    c = res["comparisons"][0]
    assert c["significant"] and c["relative_lift"] == pytest.approx(0.16)
    assert c["absolute_lift"] == pytest.approx(0.008)
    assert res["problems"] == [] and res["srm"]["mismatch"] is False


def test_analyze_multiple_variants_bonferroni():
    groups = [
        {"name": "A", "visitors": 8000, "conversions": 400},
        {"name": "B", "visitors": 8000, "conversions": 445},
        {"name": "C", "visitors": 8000, "conversions": 480},
    ]
    res = mod.analyze(groups)
    assert any("Bonferroni" in w for w in res["warnings"])
    by = {c["variant"]: c for c in res["comparisons"]}
    assert by["B"]["confidence"] == pytest.approx(0.975)
    assert not by["B"]["significant"] and by["C"]["p_value"] < 0.025


def test_analyze_problems():
    res = mod.analyze(
        [{"name": "A", "visitors": 100, "conversions": 120}, {"name": "B", "visitors": 100, "conversions": 5}]
    )
    assert res["problems"] and res["comparisons"] == []
    res = mod.analyze(
        [{"name": "A", "visitors": 10000, "conversions": 500}, {"name": "B", "visitors": 9000, "conversions": 520}]
    )
    assert res["srm"]["mismatch"] and any("sample ratio mismatch" in p for p in res["problems"])
    res = mod.analyze(
        [{"name": "A", "visitors": 50, "conversions": 2}, {"name": "B", "visitors": 50, "conversions": 4}]
    )
    assert any("normal approximation" in w for w in res["warnings"])


def test_read_groups_aggregated_and_rows():
    g = mod.order_control(mod.read_groups(str(AB / "aggregated.csv")), "original")
    assert g[0] == {"name": "original", "visitors": 10000, "conversions": 500}
    g = mod.order_control(mod.read_groups(str(AB / "users.csv"), converted_col="purchased"), None)
    assert [x["name"] for x in g] == ["A", "B"]
    assert g[0]["visitors"] == 200 and g[0]["conversions"] == 20 and g[1]["conversions"] == 40


def test_read_groups_errors(tmp_path):
    with pytest.raises(ValueError, match="variant/group"):
        mod.read_groups(str(write_csv(tmp_path, "x,y\n1,2\n")))
    with pytest.raises(ValueError, match="converted"):
        mod.read_groups(str(write_csv(tmp_path, "variant,foo\nA,1\n", "b.csv")))
    with pytest.raises(ValueError, match="not found"):
        mod.order_control([{"name": "A"}], "Z")


def test_control_detection_prefers_control_name(tmp_path):
    f = write_csv(tmp_path, "group,users,orders\nB,100,12\ncontrol,100,10\n")
    g = mod.order_control(mod.read_groups(str(f)), None)
    assert g[0]["name"] == "control"


def test_cli_analyze():
    r = run_script(SKILL, SCRIPT, "analyze", "--control", "10000", "500", "--variant", "10000", "580")
    assert r.returncode == 0 and "+16.0%" in r.stdout and "converts better" in r.stdout
    r = run_script(SKILL, SCRIPT, "analyze", "--control", "10000", "500", "--variant", "9000", "520")
    assert r.returncode == 1 and "MISMATCH" in r.stdout
    r = run_script(SKILL, SCRIPT, "analyze", "--csv", str(AB / "aggregated.csv"), "--json")
    data = json.loads(r.stdout)
    assert data["comparisons"][0]["variant"] == "new_checkout"
    r = run_script(
        SKILL, SCRIPT, "analyze", "--control", "9000", "450", "--variant", "1000", "50", "--expected-split", "90,10"
    )
    assert r.returncode == 0 and "no significant difference" in r.stdout
    assert run_script(SKILL, SCRIPT, "analyze", "--control", "10", "1").returncode == 2
    assert (
        run_script(
            SKILL, SCRIPT, "analyze", "--control", "10", "1", "--variant", "10", "1", "--expected-split", "1,2,3"
        ).returncode
        == 2
    )


def test_cli_sample_size():
    r = run_script(SKILL, SCRIPT, "sample-size", "--baseline", "0.05", "--mde", "0.1", "--daily-traffic", "3000")
    assert r.returncode == 0 and "31,234 per group" in r.stdout and "21 days" in r.stdout
    r = run_script(SKILL, SCRIPT, "sample-size", "--baseline", "0.05", "--mde", "0.1", "--groups", "3", "--json")
    data = json.loads(r.stdout)
    assert data["alpha"] == pytest.approx(0.025) and data["total"] == data["per_group"] * 3
    assert run_script(SKILL, SCRIPT, "sample-size", "--baseline", "1.5", "--mde", "0.1").returncode == 2


def test_ratio_one_matches_equal_split():
    assert mod.sample_size(0.05, 0.1, ratio=1.0) == mod.sample_size(0.05, 0.1)
    with pytest.raises(ValueError):
        mod.sample_size(0.05, 0.1, ratio=0)


def test_unequal_split_needs_more_total_traffic():
    equal = mod.sample_size(0.05, 0.1)
    control, variant = mod.split_sample_sizes(0.05, 0.1, [90, 10])
    assert variant == pytest.approx(control / 9, abs=1)
    # the small arm dominates: the variant needs more than an equal-split group would
    # need, and the total is several times the equal-split total (about (1+k)^2/(4k) = 2.78x)
    assert variant > equal / 2 and variant < equal
    assert (control + variant) / (2 * equal) == pytest.approx(100**2 / (4 * 90 * 10), rel=0.05)


def test_split_is_symmetric_in_total():
    a = sum(mod.split_sample_sizes(0.05, 0.1, [80, 20]))
    b = sum(mod.split_sample_sizes(0.05, 0.1, [20, 80]))
    assert a == pytest.approx(b, rel=0.05)


def test_split_three_groups_uses_largest_control_need():
    sizes = mod.split_sample_sizes(0.05, 0.1, [50, 25, 25], alpha=0.025)
    assert len(sizes) == 3
    assert sizes[1] == sizes[2] == pytest.approx(sizes[0] / 2, abs=1)


def test_cli_sample_size_split():
    r = run_script(
        SKILL,
        SCRIPT,
        "sample-size",
        "--baseline",
        "0.05",
        "--mde",
        "0.1",
        "--split",
        "90,10",
        "--daily-traffic",
        "5000",
        "--json",
    )
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)
    control, variant = res["per_group_by_split"]
    assert res["split"] == [0.9, 0.1]
    assert res["total"] == control + variant
    assert res["total"] > res["total_with_equal_split"]
    assert res["days"] == -(-res["total"] // 5000)
    text = run_script(SKILL, SCRIPT, "sample-size", "--baseline", "0.05", "--mde", "0.1", "--split", "90/10")
    assert text.returncode == 0 and "control" in text.stdout and "(10%)" in text.stdout


def test_cli_sample_size_equal_split_matches_default_and_bad_split():
    eq = json.loads(
        run_script(
            SKILL, SCRIPT, "sample-size", "--baseline", "0.05", "--mde", "0.1", "--split", "50,50", "--json"
        ).stdout
    )
    default = json.loads(
        run_script(SKILL, SCRIPT, "sample-size", "--baseline", "0.05", "--mde", "0.1", "--json").stdout
    )
    assert eq == default
    for bad in ("100", "90,0", "a,b"):
        r = run_script(SKILL, SCRIPT, "sample-size", "--baseline", "0.05", "--mde", "0.1", "--split", bad)
        assert r.returncode == 2, bad
