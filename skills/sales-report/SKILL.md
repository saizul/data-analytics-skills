---
name: sales-report
description: Produce a Markdown sales report from an orders CSV (one row per order or per line item) - revenue, orders, average order value, units, customers, repeat customer rate and orders per customer, a daily/weekly/monthly trend with new vs returning customers and change vs previous period, and top products by revenue with share. Excludes cancelled/refunded/failed orders by default, reads Bangla digits and lakh/crore amounts, can print amounts as 1,00,000, never prints customer identifiers. Use when the user asks for a sales summary, weekly or monthly report, revenue trend, AOV, best-selling products, repeat rate, or "how did we do this month" from a Shopify, WooCommerce, Daraz, POS or spreadsheet export.
license: MIT
compatibility: Python 3.8+ standard library only. Works offline on local files.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Sales report

A repeatable sales summary from a plain orders export: the same definitions every week,
so changes reflect the business, not the spreadsheet.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Make a sales report for October", "weekly sales summary", "what are our top products"
- "What is our AOV / repeat rate?", "compare this month with last month"
- A recurring report for the owner, investors or a WhatsApp/Slack update

## When not to use

- Retention over time by first-purchase month: `cohort-retention`
- Website traffic and conversion: `ga4-export-analysis`
- Spotting unusual days automatically: `anomaly-alerts`
- Accounting (VAT, COGS, payouts): this is a management report, not bookkeeping

## Workflow

1. **Profile the export** (`csv-profiling`) and fix formats with `data-cleaning` if amounts
   or dates are mixed. Know what one row is.
2. **Confirm definitions** (or read them from `kpi-definitions` if the user has a dictionary):
   - Revenue = which amount? Line items use `unit_price x quantity`; order-level files use
     the total column. Shopify repeats order totals only on the first line: use line prices.
   - Which statuses count? Default drops cancelled, canceled, refunded, failed, voided,
     returned, declined. For cash on delivery, consider counting only `delivered`.
   - Time period and currency.
3. **Run** (columns are auto-detected; override when detection is wrong):
   ```bash
   python3 scripts/sales_report.py orders.csv --currency BDT
   python3 scripts/sales_report.py orders.csv --period week --from 2026-10-01 --to 2026-10-31
   python3 scripts/sales_report.py orders.csv --lakh --top 5
   python3 scripts/sales_report.py export.csv --order-col Name --date-col "Created at" \
     --product-col "Lineitem name" --quantity-col "Lineitem quantity" --price-col "Lineitem price" \
     --status-col "Financial Status"
   python3 scripts/sales_report.py orders.csv --exclude-status cancelled,returned,pending
   python3 scripts/sales_report.py orders.csv --json > report.json
   ```
   Platform column names: [references/export-columns.md](references/export-columns.md).
4. **Check the numbers** before writing conclusions: compare total revenue and order count with
   the platform dashboard for the same dates. Differences usually come from status filters,
   timezone (UTC vs Asia/Dhaka), or refunds.
5. **Write the narrative**: headline change, what drove it (orders vs AOV, new vs returning,
   which products), one or two actions. Mention the notes the script prints (excluded rows,
   orders without customer id, incomplete last period).

## Output

The script prints summary, trend and product tables. Lead with a short narrative:

```markdown
**October 2026: BDT 4,12,500 revenue (+18% vs September) from 286 orders.**
- Growth came from more orders (+21%); AOV dipped slightly to BDT 1,442.
- Returning customers made 34% of buyers, up from 27%. Repeat rate (all time): 29%.
- Cotton Saree is 41% of revenue; Silk Scarf units doubled after the Facebook campaign.
- Note: 12 cancelled and 4 refunded orders excluded; October 31 data ends at 18:00.
```
