---
name: data-cleaning
description: Clean messy CSV exports safely with a dry run first - trim and collapse whitespace, blank null tokens (N/A, null, -), convert Bangla digits, normalise numbers with lakh/crore or western grouping, currency symbols (Tk, BDT, $), accounting negatives and "1.5 lakh", convert mixed dates (dd/mm/yyyy, mm/dd/yyyy, 12 Jan 2026, YYYYMMDD) to ISO 8601, fix case variants, snake_case headers, and remove exact or key-based duplicates after normalisation. Use when the user asks to clean, tidy, standardise, dedupe or fix a CSV, when sums or dates are wrong because of formatting, or when csv-profiling reported duplicates, mixed formats or text numbers.
license: MIT
compatibility: Python 3.8+ standard library only. Works offline; never overwrites the input file.
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# Data cleaning

Make the file analysable without losing information. Every run is a dry run unless `--out`
is given, the input is never overwritten, and values that cannot be parsed are left as they
were and reported, never guessed.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Clean this CSV", "remove duplicates", "standardise the dates", "fix the amounts"
- Amounts like `1,00,000`, `৳ ২,৫০০`, `Tk 900`, `(300)`, `1.5 lakh` that do not sum
- Dates mixing `05/01/2026`, `2026-01-06` and `8-1-2026`
- After `csv-profiling` reported duplicates, mixed formats, whitespace or case variants

## When not to use

- Understanding a file you have not looked at yet: run `csv-profiling` first
- Merging several files, pivoting or reshaping: do that after cleaning, in code the user reviews
- Data that must stay byte-identical (signed exports, audit evidence): work on a copy

## Workflow

1. **Profile first** (`csv-profiling`) and confirm with the user:
   - date order (`dmy` default, `mdy` for US exports), and decimal style (`--decimal-comma` for `1.234,56`)
   - what one row is, and which columns form the key for duplicates (order id? order id + product?)
2. **Dry run** (writes nothing):
   ```bash
   python3 scripts/clean_csv.py data.csv
   python3 scripts/clean_csv.py data.csv --case City=title --snake-headers
   python3 scripts/clean_csv.py data.csv --dedupe key --key "Order ID" --keep last
   python3 scripts/clean_csv.py data.csv --number-cols Amount,Qty --date-cols "Order Date"
   ```
   Number and date columns are auto-detected (80% of values parse; leading-zero codes such
   as phone numbers are never converted). Pass `--number-cols ''` to disable.
3. **Review the report with the user**: duplicates removed (with line numbers), values left
   unparseable, ambiguous dates, ragged rows. Decision points:
   - Ragged rows: fix quoting at the source; the script pads short rows but cannot split merged fields.
   - Unparseable values: ask whether to blank them, fix them by hand, or keep them.
   - Key-based dedupe drops real data if the key is wrong; show the duplicate pairs first.
4. **Write a new file** once the user agrees:
   ```bash
   python3 scripts/clean_csv.py data.csv --case City=title --out data.clean.csv
   python3 scripts/clean_csv.py data.csv --out data.clean.csv --excel-bom   # Excel shows Bangla text
   python3 scripts/clean_csv.py data.csv --out data.clean.csv --strict      # exit 1 if problems remain
   ```
5. **Verify**: profile the cleaned file and compare row counts and totals with the original:
   `python3 ../csv-profiling/scripts/profile_csv.py data.clean.csv` (path relative to this folder
   when both skills are installed side by side).

Rules for numbers and dates are in [references/normalisation-rules.md](references/normalisation-rules.md).

## Output

```markdown
Dry run on orders.csv (11 rows):
- Amount: 6 values normalised (1,00,000 -> 100000, ৳ ২,৫০০ -> 2500, (300) -> -300, 1.5 lakh -> 150000)
- Order Date: 10 dates converted to ISO; 8 were ambiguous and read as day-first
- 1 exact duplicate removed (line 7 = line 6); 3 cells trimmed; N/A blanked in Status
- Left unchanged: Amount "abc" on line 6 - please confirm what it should be

Run with `--out orders.clean.csv` to write the file (the original stays untouched).
```
