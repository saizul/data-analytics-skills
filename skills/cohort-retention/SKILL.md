---
name: cohort-retention
description: Build monthly or weekly cohort retention tables from an orders, subscriptions or user-activity CSV - cohort = period of each customer's first order or activity, retention by period offset (M0, M1, M2 ...), blank cells for periods not observable yet, partial current period marked and excluded from the size-weighted average, optional cumulative revenue per customer (LTV curve), Markdown, CSV or JSON output. Use when the user asks about retention, repeat purchase behaviour, churn by cohort, customer lifetime value curves, "do customers come back", or wants a cohort chart from a Shopify/WooCommerce/app export without a BI tool.
license: MIT
compatibility: Python 3.8+ standard library only. Works offline on local files.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Cohort retention

Group customers by when they first bought (or signed up), then measure what share is active
again in each later period. Unlike an overall repeat rate, cohorts show whether retention is
improving over time.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Show retention by cohort", "how many customers buy again after their first order"
- "Is retention getting better since we launched the loyalty programme?"
- LTV curves: cumulative revenue per customer by months since first order
- App/product activity logs: one row per user per active day or event

## When not to use

- One overall number (repeat customer rate, AOV): `sales-report`
- Subscription MRR movements (expansion, contraction): needs plan data; out of scope here
- Fewer than ~30 customers per cohort: the percentages are noise; say so and show counts

## Workflow

1. **Check the input** (run `csv-profiling` if not done): one row per order or activity, a
   stable customer id, a date. Guest checkouts: use phone or email; normalise first with
   `data-cleaning` (`+8801711...` and `01711...` must match).
2. **Decide with the user**:
   - Activity definition: any order? only paid/delivered? Cancelled/refunded rows are dropped
     automatically when a status column exists.
   - Grain: monthly for e-commerce (purchase cycles are long), weekly for apps.
   - Does the export start at the true beginning? If not, the first cohort contains old
     customers whose real first order is earlier: exclude it or note it.
3. **Run**:
   ```bash
   python3 scripts/cohort_retention.py orders.csv
   python3 scripts/cohort_retention.py orders.csv --period week --max-periods 8
   python3 scripts/cohort_retention.py orders.csv --value-col total --currency BDT   # + LTV table
   python3 scripts/cohort_retention.py orders.csv --user-col Email --date-col "Created at" --min-size 20
   python3 scripts/cohort_retention.py orders.csv --format csv > cohorts.csv            # for a sheet/heatmap
   ```
4. **Interpret** with [references/reading-cohorts.md](references/reading-cohorts.md):
   - M0 is always 100%. Read M1 down the column: is it rising for newer cohorts?
   - Blank = not observable yet; `*` = current, unfinished period (excluded from the average).
   - Compare cohorts of similar size; mark campaign months (Eid, 11.11, Black Friday) that
     bring many one-time buyers.
5. **Recommend** one or two actions tied to the biggest drop (usually M0 -> M1).

## Output

```markdown
| Cohort | Users | M0 | M1 | M2 | M3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-01 | 412 | 100% | 18% | 12% | 10% |
| 2026-02 | 380 | 100% | 22% | 15% | 9%* |
| **Weighted avg** | | 100% | 20% | 13% | 10% |
```

Then three bullets: the headline (e.g. "about 1 in 5 customers buys again in the next month"),
the trend across cohorts, and the caveats (partial periods, small cohorts, export start date).
