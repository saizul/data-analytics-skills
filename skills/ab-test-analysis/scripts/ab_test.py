#!/usr/bin/env python3
"""A/B test maths for conversion rates: lift, two-proportion z-test, confidence interval,
sample ratio mismatch (SRM) check, and sample size / duration planning.

  ab_test.py analyze --control 10000 500 --variant 10000 560
  ab_test.py analyze --csv results.csv            # variant,visitors,conversions  or one row per user
  ab_test.py sample-size --baseline 0.05 --mde 0.10 --daily-traffic 2000
  ab_test.py sample-size --baseline 0.05 --mde 0.10 --split 90,10   # unequal allocation

Python 3.8+ standard library only (statistics.NormalDist, math).
Exit codes: 0 = ok, 1 = sample ratio mismatch or invalid counts (do not trust the result), 2 = error.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
from statistics import NormalDist

N = NormalDist()


def z_test(n1: int, x1: int, n2: int, x2: int, alternative: str = "two-sided") -> dict:
    """Pooled two-proportion z-test of variant (2) against control (1)."""
    p1, p2 = x1 / n1, x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se if se > 0 else 0.0
    if alternative == "greater":
        p = 1 - N.cdf(z)
    elif alternative == "less":
        p = N.cdf(z)
    else:
        p = 2 * (1 - N.cdf(abs(z)))
    return {"z": z, "p_value": min(max(p, 0.0), 1.0)}


def diff_ci(n1: int, x1: int, n2: int, x2: int, confidence: float = 0.95) -> tuple[float, float]:
    """Unpooled (Wald) confidence interval for p2 - p1."""
    p1, p2 = x1 / n1, x2 / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    zc = N.inv_cdf(1 - (1 - confidence) / 2)
    d = p2 - p1
    return d - zc * se, d + zc * se


def gammaincc(a: float, x: float) -> float:
    """Regularised upper incomplete gamma Q(a, x) (Numerical Recipes series / continued fraction)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1:
        ap, s, delta = a, 1.0 / a, 1.0 / a
        for _ in range(500):
            ap += 1
            delta *= x / ap
            s += delta
            if abs(delta) < abs(s) * 1e-15:
                break
        return max(0.0, 1.0 - s * math.exp(-x + a * math.log(x) - gln))
    b = x + 1 - a
    c, d = 1e300, 1 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        h *= d * c
        if abs(d * c - 1) < 1e-15:
            break
    return min(1.0, math.exp(-x + a * math.log(x) - gln) * h)


def srm_check(visitors: list[int], weights: list[float] | None = None) -> dict:
    """Chi-square goodness of fit of the visitor split against the planned weights."""
    k = len(visitors)
    weights = weights or [1.0] * k
    total, wsum = sum(visitors), sum(weights)
    expected = [total * w / wsum for w in weights]
    chi2 = sum((o - e) ** 2 / e for o, e in zip(visitors, expected) if e > 0)
    p = gammaincc((k - 1) / 2, chi2 / 2)
    return {"chi2": chi2, "p_value": p, "expected": expected}


def sample_size(
    baseline: float,
    mde: float,
    relative: bool = True,
    alpha: float = 0.05,
    power: float = 0.8,
    alternative="two-sided",
    ratio: float = 1.0,
) -> int:
    """Control visitors needed to detect the change with a two-proportion z-test.

    ratio = variant visitors / control visitors (1.0 = equal split, 1/9 = a 90/10 holdout).
    The variant then needs ceil(result * ratio) visitors.
    """
    p1 = baseline
    p2 = baseline * (1 + mde) if relative else baseline + mde
    if not (0 < p1 < 1 and 0 < p2 < 1) or p1 == p2:
        raise ValueError(f"baseline {p1} and target {p2} must be different rates between 0 and 1")
    if ratio <= 0:
        raise ValueError("ratio must be > 0")
    za = N.inv_cdf(1 - alpha / 2) if alternative == "two-sided" else N.inv_cdf(1 - alpha)
    zb = N.inv_cdf(power)
    pbar = (p1 + ratio * p2) / (1 + ratio)
    num = za * math.sqrt(pbar * (1 - pbar) * (1 + 1 / ratio)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2) / ratio)
    return math.ceil(num**2 / (p2 - p1) ** 2)


def split_sample_sizes(
    baseline: float,
    mde: float,
    weights: list[float],
    relative: bool = True,
    alpha: float = 0.05,
    power: float = 0.8,
    alternative="two-sided",
) -> list[int]:
    """Visitors per group for a planned split; weights[0] is the control.

    Every variant must reach the power against the control, so the control size is the
    largest any variant needs and each variant gets its share of that.
    """
    control = max(sample_size(baseline, mde, relative, alpha, power, alternative, w / weights[0]) for w in weights[1:])
    return [control] + [math.ceil(control * w / weights[0] - 1e-9) for w in weights[1:]]


def analyze(groups: list[dict], alpha: float = 0.05, alternative: str = "two-sided", weights=None) -> dict:
    """groups[0] is the control. Each group: name, visitors, conversions."""
    problems, warnings = [], []
    for g in groups:
        if g["visitors"] <= 0:
            problems.append(f"{g['name']}: visitors must be > 0")
        elif not 0 <= g["conversions"] <= g["visitors"]:
            problems.append(f"{g['name']}: conversions ({g['conversions']}) must be between 0 and visitors")
    if problems:
        return {"groups": groups, "comparisons": [], "problems": problems, "warnings": warnings, "srm": None}
    control = groups[0]
    n_comp = len(groups) - 1
    adj_alpha = alpha / n_comp if n_comp > 1 else alpha
    if n_comp > 1:
        warnings.append(f"{n_comp} variants vs control: Bonferroni-adjusted alpha = {adj_alpha:.4g}")
    for g in groups:
        g["rate"] = g["conversions"] / g["visitors"]
        if g["conversions"] < 10 or g["visitors"] - g["conversions"] < 10:
            warnings.append(
                f"{g['name']}: fewer than 10 conversions or non-conversions; the normal approximation is rough"
            )
    comps = []
    for g in groups[1:]:
        t = z_test(control["visitors"], control["conversions"], g["visitors"], g["conversions"], alternative)
        lo, hi = diff_ci(control["visitors"], control["conversions"], g["visitors"], g["conversions"], 1 - adj_alpha)
        abs_lift = g["rate"] - control["rate"]
        rel = abs_lift / control["rate"] if control["rate"] > 0 else None
        needed = None
        if rel and 0 < g["rate"] < 1:
            try:
                needed = sample_size(control["rate"], abs_lift, False, adj_alpha, 0.8, alternative)
            except ValueError:
                needed = None
        comps.append(
            {
                "variant": g["name"],
                "absolute_lift": abs_lift,
                "relative_lift": rel,
                "ci_low": lo,
                "ci_high": hi,
                "confidence": 1 - adj_alpha,
                "z": t["z"],
                "p_value": t["p_value"],
                "significant": t["p_value"] < adj_alpha,
                "needed_per_group_for_80pct_power": needed,
            }
        )
    srm = srm_check([g["visitors"] for g in groups], weights)
    srm["mismatch"] = srm["p_value"] < 0.001
    if srm["mismatch"]:
        problems.append(
            f"sample ratio mismatch: visitor split {[g['visitors'] for g in groups]} is unlikely under the planned "
            f"split (chi2 {srm['chi2']:.1f}, p {srm['p_value']:.2g}); fix assignment/tracking before reading results"
        )
    return {
        "groups": groups,
        "comparisons": comps,
        "alpha": alpha,
        "alternative": alternative,
        "srm": srm,
        "problems": problems,
        "warnings": warnings,
    }


def read_groups(path: str, group_col=None, visitors_col=None, conversions_col=None, converted_col=None) -> list[dict]:
    """Aggregated CSV (group, visitors, conversions) or row-level CSV (group, converted 0/1)."""
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("CSV has no data rows")
    header = list(rows[0].keys())
    by = {re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_"): h for h in header}

    def find(explicit, names, role):
        if explicit:
            if explicit not in header:
                raise ValueError(f"column {explicit!r} not found; columns are {header}")
            return explicit
        return next((by[n] for n in names if n in by), None)

    gcol = find(group_col, ["variant", "group", "arm", "variation", "experiment_variant", "bucket"], "group")
    if not gcol:
        raise ValueError(f"no variant/group column found (use --group-col); columns are {header}")
    vcol = find(visitors_col, ["visitors", "users", "sessions", "participants", "exposures", "n", "trials"], "visitors")
    ccol = find(conversions_col, ["conversions", "converted_users", "orders", "purchases", "successes", "x"], "conv")
    order: list[str] = []
    agg: dict = {}
    if vcol and ccol and not converted_col:
        for r in rows:
            name = r[gcol].strip()
            if name not in agg:
                order.append(name)
                agg[name] = [0, 0]
            agg[name][0] += int(float(r[vcol].replace(",", "")))
            agg[name][1] += int(float(r[ccol].replace(",", "")))
    else:
        kcol = find(converted_col, ["converted", "conversion", "is_converted", "purchased", "success", "outcome"], "c")
        if not kcol:
            raise ValueError("need visitors+conversions columns or a 0/1 converted column (see --help)")
        for r in rows:
            name = r[gcol].strip()
            if name not in agg:
                order.append(name)
                agg[name] = [0, 0]
            agg[name][0] += 1
            agg[name][1] += r[kcol].strip().lower() in ("1", "true", "yes", "y", "converted")
    return [{"name": n, "visitors": agg[n][0], "conversions": agg[n][1]} for n in order]


def order_control(groups: list[dict], control: str | None) -> list[dict]:
    if control:
        match = [g for g in groups if g["name"] == control]
        if not match:
            raise ValueError(f"control {control!r} not found; groups are {[g['name'] for g in groups]}")
    else:
        match = [g for g in groups if g["name"].lower() in ("control", "a", "baseline", "original", "0")] or groups[:1]
    c = match[0]
    return [c] + [g for g in groups if g is not c]


def fmt_p(p: float) -> str:
    return "< 0.0001" if p < 1e-4 else f"{p:.4f}"


def render_analysis(res: dict) -> str:
    out = ["# A/B test result", ""]
    out += ["| Group | Visitors | Conversions | Rate |", "| --- | ---: | ---: | ---: |"]
    for g in res["groups"]:
        rate = f"{g['rate'] * 100:.2f}%" if "rate" in g else "-"
        out.append(f"| {g['name']} | {g['visitors']:,} | {g['conversions']:,} | {rate} |")
    if res["comparisons"]:
        out += [
            "",
            "| Variant vs control | Lift (relative) | Lift (points) | CI for difference | p-value | Significant |",
        ]
        out.append("| --- | ---: | ---: | --- | ---: | --- |")
        for c in res["comparisons"]:
            rel = "-" if c["relative_lift"] is None else f"{c['relative_lift'] * 100:+.1f}%"
            ci = f"{c['ci_low'] * 100:+.2f} to {c['ci_high'] * 100:+.2f} pts ({c['confidence'] * 100:.4g}%)"
            sig = "yes" if c["significant"] else "no"
            out.append(
                f"| {c['variant']} | {rel} | {c['absolute_lift'] * 100:+.2f} | {ci} | {fmt_p(c['p_value'])} | {sig} |"
            )
        out.append("")
        for c in res["comparisons"]:
            if c["significant"]:
                direction = "better" if c["absolute_lift"] > 0 else "worse"
                out.append(f"- **{c['variant']}** converts {direction} than control (p {fmt_p(c['p_value'])}).")
            else:
                need = c["needed_per_group_for_80pct_power"]
                hint = f" Detecting a lift this small needs about {need:,} visitors per group." if need else ""
                out.append(f"- **{c['variant']}**: no significant difference yet.{hint}")
    if res.get("srm"):
        s = res["srm"]
        status = "MISMATCH" if s["mismatch"] else "ok"
        out.append(f"- Sample ratio check: {status} (chi2 {s['chi2']:.2f}, p {fmt_p(s['p_value'])})")
    for w in res["warnings"]:
        out.append(f"- Note: {w}")
    for pr in res["problems"]:
        out.append(f"- **Problem:** {pr}")
    return "\n".join(out) + "\n"


def parse_weights(text: str | None, k: int) -> list[float] | None:
    if not text:
        return None
    w = [float(x) for x in re.split(r"[,/:]", text) if x.strip()]
    if len(w) != k or any(x <= 0 for x in w):
        raise ValueError(f"--expected-split needs {k} positive numbers, e.g. 50,50")
    return w


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Conversion A/B tests: lift, z-test p-value, CI, SRM, sample size.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analyse results")
    a.add_argument("--control", nargs=2, type=int, metavar=("VISITORS", "CONVERSIONS"))
    a.add_argument("--variant", nargs=2, type=int, action="append", metavar=("VISITORS", "CONVERSIONS"))
    a.add_argument("--csv", help="CSV: variant,visitors,conversions or one row per user with a 0/1 converted column")
    a.add_argument("--control-name", help="which CSV group is the control (default: control/A or the first row)")
    a.add_argument("--group-col", help="CSV group column")
    a.add_argument("--visitors-col", help="CSV visitors column")
    a.add_argument("--conversions-col", help="CSV conversions column")
    a.add_argument("--converted-col", help="CSV 0/1 column for row-level data")
    a.add_argument("--alpha", type=float, default=0.05, help="significance level (default 0.05)")
    a.add_argument("--alternative", choices=["two-sided", "greater", "less"], default="two-sided")
    a.add_argument("--expected-split", help="planned traffic split, e.g. 50,50 or 90,10 (default equal)")
    a.add_argument("--json", action="store_true", help="print JSON")
    s = sub.add_parser("sample-size", help="visitors per group and test duration")
    s.add_argument("--baseline", type=float, required=True, help="current conversion rate, e.g. 0.04")
    s.add_argument("--mde", type=float, required=True, help="minimum detectable effect (relative, 0.1 = +10%%)")
    s.add_argument("--absolute", action="store_true", help="--mde is in absolute points (0.005 = +0.5 pts)")
    s.add_argument("--alpha", type=float, default=0.05)
    s.add_argument("--power", type=float, default=0.8)
    s.add_argument("--groups", type=int, default=2, help="groups including control (default 2; Bonferroni for >2)")
    s.add_argument("--alternative", choices=["two-sided", "greater"], default="two-sided")
    s.add_argument(
        "--split", help="planned traffic split, control first, e.g. 90,10 or 50,25,25 (default equal; sets --groups)"
    )
    s.add_argument("--daily-traffic", type=float, help="eligible visitors per day across all groups")
    s.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    try:
        if args.cmd == "sample-size":
            weights = None
            if args.split:
                weights = [float(x) for x in re.split(r"[,/:]", args.split) if x.strip()]
                if len(weights) < 2 or any(w <= 0 for w in weights):
                    raise ValueError("--split needs 2 or more positive numbers, control first, e.g. 90,10")
                args.groups = len(weights)
            alpha = args.alpha / (args.groups - 1) if args.groups > 2 else args.alpha
            target = args.baseline * (1 + args.mde) if not args.absolute else args.baseline + args.mde
            if weights and len(set(weights)) > 1:
                sizes = split_sample_sizes(
                    args.baseline, args.mde, weights, not args.absolute, alpha, args.power, args.alternative
                )
            else:
                sizes = [sample_size(args.baseline, args.mde, not args.absolute, alpha, args.power, args.alternative)]
                sizes *= args.groups
            n, total = max(sizes), sum(sizes)
            res = {
                "per_group": n,
                "total": total,
                "baseline": args.baseline,
                "target": target,
                "alpha": alpha,
                "power": args.power,
            }
            if len(set(sizes)) > 1:
                share = sum(weights)
                res["split"] = [round(w / share, 4) for w in weights]
                res["per_group_by_split"] = sizes
                equal = sample_size(args.baseline, args.mde, not args.absolute, alpha, args.power, args.alternative)
                res["total_with_equal_split"] = equal * args.groups
            if args.daily_traffic:
                res["days"] = math.ceil(total / args.daily_traffic)
                res["days_rounded_to_weeks"] = math.ceil(res["days"] / 7) * 7
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(
                    f"Baseline {args.baseline * 100:.2f}% -> target {target * 100:.2f}% "
                    f"(alpha {alpha:.4g}, power {args.power:.0%}, {args.alternative})"
                )
                if "per_group_by_split" in res:
                    parts = ", ".join(
                        f"{name} {size:,} ({share:.0%})"
                        for name, size, share in zip(
                            ["control"] + [f"variant {c}" for c in "BCDEFGH"], sizes, res["split"]
                        )
                    )
                    print(f"Visitors needed: {parts}; {total:,} in total")
                    print(
                        f"An equal split would need {res['total_with_equal_split']:,} in total "
                        f"(this split needs {total / res['total_with_equal_split']:.2f}x that traffic)"
                    )
                else:
                    print(f"Visitors needed: {n:,} per group, {total:,} in total")
                if "days" in res:
                    print(
                        f"Duration: {res['days']} days at {args.daily_traffic:,.0f}/day; "
                        f"run {res['days_rounded_to_weeks']} days to cover full weeks"
                    )
            return 0
        if args.csv:
            groups = read_groups(args.csv, args.group_col, args.visitors_col, args.conversions_col, args.converted_col)
            groups = order_control(groups, args.control_name)
        else:
            if not args.control or not args.variant:
                raise ValueError("give --control V C and --variant V C, or --csv FILE")
            groups = [{"name": "control", "visitors": args.control[0], "conversions": args.control[1]}]
            names = "BCDEFGH"
            for i, (v, c) in enumerate(args.variant):
                groups.append(
                    {
                        "name": f"variant {names[i]}" if len(args.variant) > 1 else "variant",
                        "visitors": v,
                        "conversions": c,
                    }
                )
        if len(groups) < 2:
            raise ValueError("need a control and at least one variant")
        res = analyze(groups, args.alpha, args.alternative, parse_weights(args.expected_split, len(groups)))
    except (OSError, UnicodeDecodeError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(render_analysis(res), end="")
    return 1 if res["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
