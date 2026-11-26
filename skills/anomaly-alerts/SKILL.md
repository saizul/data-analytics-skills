---
name: anomaly-alerts
description: Detect unusual days in daily metric CSVs (revenue, orders, sessions, signups, sign-ins, ad spend) with a robust rolling median and MAD z-score, optional same-weekday baseline for weekly seasonality, minimum relative and absolute change filters, missing-day detection, spike/drop direction filter, and a --last N mode with exit code 1 for cron or CI alerts and one-line alert messages for Slack, email or WhatsApp. Use when the user asks whether a drop or spike is unusual, wants to find anomalies or outliers in a time series, set up daily metric alerts or monitoring without a BI tool, or investigate "sales suddenly fell yesterday".
license: MIT
compatibility: Python 3.8+ standard library only. Works offline; sending alerts is left to the user's own tooling.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Anomaly alerts

Tell real problems from normal noise. The median and MAD baseline ignores past spikes, so
one Eid sale does not hide the next tracking outage.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Revenue dropped yesterday - is that unusual?", "find anomalies in this daily data"
- "Alert me when orders or sessions drop" (a daily cron job or CI schedule)
- Checking a GA4 Date export, a daily sales sheet, ad spend or sign-up counts

## When not to use

- Explaining why something changed: use `sales-report` (products, new vs returning) or
  `ga4-export-analysis` (sources, landing pages) for the anomalous days
- Comparing two variants in an experiment: `ab-test-analysis`
- Hourly or real-time monitoring: aggregate to days first, or use a monitoring tool

## Workflow

1. **Get a daily series**: one row per date with numeric columns (`date,revenue,orders`).
   A GA4 report with the Date dimension or a POS daily summary works as is. An orders export
   (one row per order with a date and amount) also works: rows with the same date are summed,
   so pass `--value-col` with the amount column.
2. **Choose the baseline with the user**:
   - Default: median of the previous 14 days, needs 7 days of history.
   - Strong weekday pattern (weekend sales, Friday dip in Bangladesh): `--seasonal weekly`
     compares with the same weekday over the previous 8 weeks (needs 4).
   - Sensitivity: `--threshold 3.5` (robust z) and `--min-change 0.2` (20%) by default; raise
     them if alerts are too noisy, add `--min-abs` for low-volume metrics.
3. **Run**:
   ```bash
   python3 scripts/detect_anomalies.py daily.csv
   python3 scripts/detect_anomalies.py daily.csv --value-col revenue --seasonal weekly
   python3 scripts/detect_anomalies.py daily.csv --direction down --min-abs 5000
   python3 scripts/detect_anomalies.py daily.csv --last 1 --format alert   # exit 1 if yesterday is unusual
   python3 scripts/detect_anomalies.py daily.csv --json > anomalies.json
   ```
4. **Triage each anomaly** with [references/tuning-and-alerting.md](references/tuning-and-alerting.md):
   missing day or a drop to near zero = tracking/export problem first; a spike on a campaign
   or holiday date = expected (note it); a drop across several metrics at once = site or
   payment outage.
5. **Set up alerting only if asked**: show the cron or CI snippet from the reference and let
   the user add their own webhook or email command. Never put webhook URLs or tokens in files
   in the repository.

## Output

```markdown
2 anomalies in the last 35 days (baseline: median of previous 14 days):

| Date | Metric | Value | Expected | Change | Type |
| --- | --- | ---: | ---: | ---: | --- |
| 2026-10-20 | revenue | 25,000 | 10,000 | +150% | spike |
| 2026-10-28 | revenue | 3,000 | 10,150 | -70% | drop |

- 20 Oct: matches the 11.11 pre-sale email, expected.
- 28 Oct: orders and sessions normal, revenue down 70% - check the payment gateway logs.
- 31 Oct is missing from the export.
```
