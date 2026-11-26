---
name: ga4-export-analysis
description: Summarise Google Analytics 4 data offline from a report CSV downloaded from the GA4 UI or from BigQuery export events (newline-delimited JSON or a JSON array) - users, sessions, engaged sessions and engagement rate, page views, key events/conversions, session conversion rate and revenue, broken down by session source/medium, landing page, device and date. Totals additive metrics and recomputes rates instead of summing them, skips Grand total rows, reconstructs sessions from user_pseudo_id + ga_session_id. Use when the user shares a GA4 export or BigQuery events sample and asks where traffic comes from, which landing pages or channels convert, why conversions dropped, or wants a traffic report without Looker Studio.
license: MIT
compatibility: Python 3.8+ standard library only. Reads local files; never calls Google APIs.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# GA4 export analysis

Turn a GA4 download into answers: which channels and landing pages bring engaged visitors
and conversions. Works on files the user already has; no API keys, no Looker Studio.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Analyse this GA4 export", "which traffic sources convert best", "top landing pages"
- "Conversions dropped last week - why?" (with a Date or source/medium report)
- BigQuery `events_*` sample exported as JSON: sessions, sources, landing pages, revenue
- Monthly traffic summary for a client or the owner

## When not to use

- Order-level revenue truth: GA4 revenue is tracked, not booked; use `sales-report` on
  the shop export and compare
- Significance of a landing-page or checkout test: `ab-test-analysis`
- Day-by-day alerting on sessions or conversions: export a Date report and use `anomaly-alerts`
- Live API access or SQL on BigQuery: out of scope (write the SQL separately and export the result)

## Workflow

1. **Get the right export** (ask the user if unclear; details in
   [references/ga4-exports.md](references/ga4-exports.md)):
   - UI: Reports > Acquisition > Traffic acquisition (dimension "Session source / medium"),
     Engagement > Landing page, or any report with Date; Share this report > Download file > CSV.
   - BigQuery: `SELECT * FROM analytics_<property>.events_2026*` for a date range, exported as
     JSON. Keep it small (a few days) for local analysis.
2. **Run**:
   ```bash
   python3 scripts/ga4_summary.py traffic_acquisition.csv
   python3 scripts/ga4_summary.py landing_pages.csv --top 20
   python3 scripts/ga4_summary.py events.ndjson --conversion-events purchase,generate_lead
   python3 scripts/ga4_summary.py events.json --keep-query --json > ga4.json
   ```
3. **Sanity-check** before interpreting:
   - Users are not additive across rows; the script does not total them.
   - "Key events" count events; a session can have several. For BigQuery input the script
     reports converting sessions / sessions as the conversion rate.
   - `(not set)` landing pages and `(direct) / (none)` that grows suddenly usually mean
     tracking or consent-mode problems, not real direct traffic.
   - Unassigned or `m.facebook.com / referral` vs `facebook / paid`: missing UTM tags.
4. **Interpret**: compare share of sessions with share of conversions/revenue per source and
   landing page. A channel with 20% of sessions and 7% of conversions needs attention (audience,
   landing page match, page speed). Use engagement rate to separate traffic quality from
   checkout problems.
5. **Recommend** concrete fixes: UTM tagging for campaigns, which landing pages to improve or
   promote, which tracking issues to fix first.

## Output

```markdown
**October 2026: 9,000 sessions, 60.7% engaged, 240 key events (2.7 per 100 sessions), BDT 5,54,000 revenue.**

| Source / medium | Sessions | Share | Engagement | Key events | Revenue |
| --- | ---: | ---: | ---: | ---: | ---: |
| google / organic | 4,200 | 46.7% | 70.0% | 126 | 3,15,000 |
| facebook / paid | 1,800 | 20.0% | 40.0% | 36 | 72,000 |

- Organic search brings half the traffic and 57% of revenue.
- Facebook paid: 20% of sessions but 13% of revenue and low engagement - check ad-to-landing page match.
- Newsletter is small but converts 3x the average: grow the list.
```
