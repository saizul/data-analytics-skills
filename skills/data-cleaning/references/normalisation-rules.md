# Normalisation rules

## Numbers

| Input | Output | Rule |
| --- | --- | --- |
| `1,250` / `1,234,567` | `1250` / `1234567` | Western grouping (groups of 3) |
| `1,00,000` / `12,34,567` | `100000` / `1234567` | South Asian lakh/crore grouping (3, then groups of 2) |
| `১,২৫০` / `২৫০০` | `1250` / `2500` | Bangla digits (U+09E6-U+09EF); Devanagari digits too |
| `৳ 1,250`, `Tk 900`, `BDT 900`, `$12.50`, `Rs. 400` | `1250`, `900`, `900`, `12.5`, `400` | Currency symbols and codes dropped (keep the currency in a separate column or the KPI definition) |
| `(300)` / `-300` | `-300` | Accounting negatives |
| `1.5 lakh` / `2 crore` / `১.৫ লাখ` / `3k` / `2.5 mn` | `150000` / `20000000` / `150000` / `3000` / `2500000` | lakh/lac/লাখ/লক্ষ = 1e5, crore/cr/কোটি = 1e7, k/হাজার = 1e3, m/mn/million = 1e6 |
| `12.5%` | `0.125` | Percent becomes a fraction |
| `1.234,56` with `--decimal-comma` | `1234.56` | European style |
| `1,2345`, `12,34,5678` | unchanged, reported | Invalid grouping is never guessed |

Integers are written without `.0`; decimals keep their precision (up to 10 places).

## Dates

| Input | Output |
| --- | --- |
| `2026-01-05`, `2026/1/5`, `2026.01.05` | `2026-01-05` |
| `05/01/2026`, `5-1-2026`, `05.01.26` | `2026-01-05` with `--date-order dmy` (default), `2026-05-01` with `mdy` |
| `13/01/2026` | `2026-01-13` either way (13 cannot be a month) |
| `12 Jan 2026`, `12-Jan-2026`, `Jan 12, 2026`, `January 12 2026` | `2026-01-12` |
| `20260112` (column name contains date/day) | `2026-01-12` |
| `2026-01-12T10:30:00Z`, `12/01/2026 2:30 PM` | `2026-01-12 10:30:00`, `2026-01-12 14:30:00` |

Timezone offsets are dropped and the wall-clock time is kept. If the export is in UTC and
the business runs on Asia/Dhaka (UTC+6), orders after 18:00 UTC belong to the next local
day: convert before daily reporting.

## Text

- Leading/trailing whitespace trimmed, runs of spaces collapsed (`--no-trim` to disable).
- Null tokens blanked: `NA`, `N/A`, `null`, `None`, `NaN`, `-`, `--`, `nil`, `#N/A`, `(not set)`.
- `--case COL=title|lower|upper` for names and cities (`dhaka` -> `Dhaka`).
- `--ascii-digits` converts Bangla digits in every column (phone numbers, ids). Off by
  default so Bangla text fields stay as written.
- `--snake-headers`: `Order Date` -> `order_date`, ` City ` -> `city`.

## Duplicates

- `--dedupe exact` (default): rows identical after normalisation (`1,250` and `1250` match).
- `--dedupe key --key "Order ID"`: one row per key; `--keep first|last` (last = latest export row).
  Rows with an empty key are always kept.
- `--dedupe none` for line-item files where repeated rows are real.
