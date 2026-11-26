---
name: csv-profiling
description: Profile any CSV export before analysing it - inferred column types (integer, number, date, datetime, boolean, code, string), null counts, unique counts and candidate keys, min/median/max/mean, IQR outliers with line numbers, date ranges with missing days and future dates, mixed formats, duplicate rows, ragged rows, whitespace and case variants. Understands Bangla digits, lakh/crore grouping and currency symbols. Use when the user shares a CSV or spreadsheet export and asks what is in it, whether the data is clean, why totals look wrong, or before building any report, cohort, KPI or dashboard from a file.
license: MIT
compatibility: Python 3.8+ standard library only. Works offline on local files.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# CSV profiling

Look at the data before you trust it. The script reads the file once and reports facts
(types, ranges, problems with line numbers) so you never guess from the first 20 rows.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "What's in this CSV?", "Is this export clean?", "Check this file before we analyse it"
- Totals do not match the source system, a chart looks wrong, a join drops rows
- First step before `sales-report`, `cohort-retention`, `anomaly-alerts` or a KPI definition
- Shopify, WooCommerce, Daraz, bKash/Nagad statements, POS, CRM or Google Sheets exports

## When not to use

- Fixing the problems: use `data-cleaning` after profiling (profile again afterwards)
- Files that are not tabular text (xlsx: ask the user to export CSV, or save as CSV first)
- GA4 downloads with `#` comment headers: use `ga4-export-analysis`

## Workflow

1. **Locate the file and ask two questions** if the answer is not obvious:
   - How are dates written (03/04/2026 = 3 April or 4 March)? Default is day-first (`dmy`).
   - What is one row (an order, a line item, a customer, a day)?
2. **Run the profiler** (read-only):
   ```bash
   python3 scripts/profile_csv.py data.csv
   python3 scripts/profile_csv.py data.csv --date-order mdy      # US-style dates
   python3 scripts/profile_csv.py data.csv --json > profile.json # for further processing
   python3 scripts/profile_csv.py data.csv --fail-on medium      # exit 1 in CI / pipelines
   python3 scripts/profile_csv.py customers.csv --redact         # hide names/phones in the output
   ```
   Use `--redact` when the file holds personal data and the values are not needed to explain problems.
   Large files are fine (one pass, in memory); for files over ~1 GB profile a sample:
   `head -n 200001 big.csv > sample.csv`.
3. **Read the issues top-down** (high, medium, low) and explain each in plain words. See
   [references/issue-guide.md](references/issue-guide.md) for what each finding usually means.
   Decision points:
   - **Ragged rows (high)**: a field contains an unquoted delimiter (often a Bangla amount
     like `৳ ২,৫০০`). Fix the export or quoting first; every other number is unreliable.
   - **Not numeric / not dates (medium)**: list the example values and line numbers; ask
     whether they are errors, placeholders or a second format.
   - **Ambiguous dates (medium)**: confirm the date order with the user before any time series.
   - **Duplicate rows (medium)**: ask whether the file is line items (duplicates may be real)
     or orders (probably an export glitch).
   - **Outliers (low)**: check the examples; a 1,00,000 order in a shop with a 1,200 average
     may be real (wholesale) or a typo. Do not drop them silently.
   - **Code columns** (phone, postcode, ids with leading zeros): keep as text everywhere.
4. **Identify the grain and keys**: a column marked `(key)` is unique per row. If no key
   exists, say what combination should be unique.
5. **Recommend next steps**: which `data-cleaning` options to run, and which analysis skill fits.

## Output

Summarise like this (do not paste the whole table for wide files; pick the columns that matter):

```markdown
**orders.csv**: 11 rows x 7 columns, one row per order. `Order ID` is not unique (1 duplicate row).

Problems to fix before analysis:
1. `Amount` has 2 non-numeric values ("abc", lines 6-7) and mixed formats (1,00,000 / ৳ ২,৫০০ / Tk 900).
2. `Order Date` mixes 3 formats; 8 dates like 05/01/2026 are ambiguous - read as 5 January (confirm).
3. `City` has case variants (Dhaka / dhaka / DHAKA).

Looks fine: dates 2026-01-05 to 2026-01-14 with no missing days; Phone kept as text.
Next: run data-cleaning with `--case City=title`, then sales-report.
```
