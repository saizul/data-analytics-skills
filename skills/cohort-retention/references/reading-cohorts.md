# Reading a cohort table

## Definitions used by the script

- **Cohort**: the month (or ISO week, starting Monday) of a user's first row in the file.
- **Period N**: the calendar period N steps after the cohort period (not "N x 30 days after
  the first order"). A customer who first buys on 31 January and again on 1 February is
  active in M1.
- **Retention in period N**: users of the cohort with at least one row in that period /
  cohort size. It is not cumulative: a customer can be inactive in M1 and active in M2.
- **Weighted average**: sum of active users / sum of cohort sizes over cohorts that have a
  complete period N. Partial (current) periods are excluded so the average is not dragged down.
- **Cumulative revenue per user** (`--value-col`): revenue from the cohort up to and including
  period N divided by the cohort size; an LTV curve.

## Typical ranges (rough, for orientation only)

| Business | M1 | M3 | M6 |
| --- | --- | --- | --- |
| Fashion / gifts e-commerce | 5-15% | 4-10% | 3-8% |
| Groceries, pharmacy, consumables | 20-40% | 15-30% | 12-25% |
| Subscription box | 70-85% | 50-65% | 35-50% |
| Consumer apps (weekly cohorts, W1/W4) | W1 20-40% | W4 10-25% | |

Your own trend matters more than benchmarks.

## Patterns

- **Newer cohorts retain better**: product or service improvements are working.
- **One weak cohort**: often a discount campaign or marketplace event that attracted
  one-time buyers. Check acquisition source.
- **Flat after M2**: a loyal core; focus on the M0 -> M1 drop (second-order offers,
  replenishment reminders, delivery experience).
- **Diagonal pattern** (one calendar month high for every cohort): seasonality (Eid,
  Pohela Boishakh, winter sale), not a retention change.
- **First cohort huge, low retention**: the export does not start at the real beginning, so
  long-time customers land in it. Exclude it.

## Caveats to state

- Customer identity: guest checkouts with different phone formats split one person into
  several "customers" and lower retention.
- Refunds/cancellations: excluded only when a status column exists.
- Small cohorts (< 30): show counts, not only percentages.
