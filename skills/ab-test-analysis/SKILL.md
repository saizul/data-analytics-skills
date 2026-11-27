---
name: ab-test-analysis
description: Analyse and plan conversion A/B tests with exact, tested maths - conversion rates, absolute and relative lift, pooled two-proportion z-test p-value (two-sided or one-sided), confidence interval for the difference, Bonferroni correction for several variants, sample ratio mismatch (SRM) chi-square check, and sample size per group plus test duration for a baseline rate and minimum detectable effect. Reads counts from the command line, an aggregated CSV (variant, visitors, conversions) or one row per user with a 0/1 converted column. Use when the user asks whether a test result is significant, which variant won, how long to run an experiment, how many visitors are needed, or why the traffic split is uneven.
license: MIT
compatibility: Python 3.8+ standard library only (statistics.NormalDist, math).
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# A/B test analysis

Decide with statistics instead of gut feeling, and plan tests that can actually detect the
change you care about. The script does the maths; you make sure the test was run properly.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Is this A/B test significant?", "variant B has 5.8% vs 5.0%, did it win?"
- "How many visitors / how many days do we need for this test?"
- "Our 50/50 test shows 10,000 vs 9,000 users - is that a problem?"
- Landing page, checkout, pricing page, email subject line (opens/clicks as conversions)

## When not to use

- Revenue per visitor or average order value tests: those need a t-test or bootstrap on
  per-user values, not a proportion test (good first issue in this repository)
- Before/after comparisons without random assignment: there is no control; say so and use
  `anomaly-alerts` or a trend comparison instead
- Multi-armed bandits or sequential designs with planned early stopping

## Workflow

1. **Planning a test** (before launch):
   ```bash
   python3 scripts/ab_test.py sample-size --baseline 0.04 --mde 0.10 --daily-traffic 2500
   python3 scripts/ab_test.py sample-size --baseline 0.04 --mde 0.005 --absolute --power 0.9
   python3 scripts/ab_test.py sample-size --baseline 0.04 --mde 0.15 --groups 3
   python3 scripts/ab_test.py sample-size --baseline 0.04 --mde 0.10 --split 90,10 --daily-traffic 2500
   ```
   `--split` (control first) plans unequal allocations such as a 90/10 holdout: it prints
   visitors per group and how much more total traffic the split costs than 50/50.
   `--mde 0.10` = detect a +10% relative change. Round the duration up to full weeks. If the
   duration is longer than ~6 weeks, test a bolder change or a higher-traffic page.
2. **Collect the facts** for a finished test: visitors and conversions per group (users, not
   sessions or page views, if users were randomised), the planned split, start/end dates,
   and whether anyone stopped the test early when it "looked significant".
3. **Analyse**:
   ```bash
   python3 scripts/ab_test.py analyze --control 10000 500 --variant 10000 580
   python3 scripts/ab_test.py analyze --control 8000 400 --variant 8000 430 --variant 8000 470
   python3 scripts/ab_test.py analyze --csv results.csv --control-name original
   python3 scripts/ab_test.py analyze --csv users.csv --converted-col purchased   # one row per user
   python3 scripts/ab_test.py analyze --csv results.csv --expected-split 90,10 --json
   ```
   Exit code 1 means the data is not trustworthy (SRM or impossible counts).
4. **Decide** using [references/interpretation.md](references/interpretation.md):
   - SRM detected: do not interpret the lift. Find the assignment or tracking bug first.
   - Significant and the CI excludes 0: ship if the lower end of the CI is still worth it.
   - Not significant: report the CI ("between -0.3 and +1.1 points"), not "no effect". If the
     test reached its planned sample size, the change is smaller than the MDE; stop.
   - Not significant and under the planned sample size: keep running to the planned size;
     do not stop early or peek repeatedly.
5. **Report** the result in business terms with the caveats.

## Output

```markdown
**Variant B wins: 5.80% vs 5.00% conversion (+16% relative, +0.80 points), p = 0.012.**
- 95% CI for the difference: +0.17 to +1.43 points, so the true lift is very likely positive.
- Traffic split is as planned (SRM check ok). 10,000 visitors per group over 14 days.
- At ~300 orders a month that is roughly 48 extra orders. Recommend shipping B.
```
