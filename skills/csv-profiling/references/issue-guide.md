# Profiling findings: what they usually mean

| Finding | Usual cause | What to do |
| --- | --- | --- |
| Rows with a different number of fields | Unquoted delimiter inside a value (amounts like `1,250` or `৳ ২,৫০০`, addresses), a line break inside a field, a `;` delimited file read as `,` | Re-export with quoting, or pass `--delimiter`. Never analyse until fixed |
| Duplicate column names | Two exports pasted side by side, Excel "Column1" artefacts | Rename before analysis; tools pick the first or last silently |
| Exact duplicate rows | Export pagination overlap, a webhook delivered twice, copy-paste | For order-level files remove them (`data-cleaning`); for line items confirm first |
| Not numeric values | Placeholders (`abc`, `TBD`, `-`), notes typed in a number cell, a second currency | Ask; blank them or fix at the source |
| Numbers stored as formatted text | Separators, currency symbols, Bangla digits, `(300)` for negatives | Normalise with `data-cleaning` so sums are correct |
| IQR outliers | Wholesale orders, test orders (1 Tk), typos (extra zero), unit mix (paisa vs taka) | Look at the lines; decide with the user; report results with and without them |
| Negative values | Refunds, returns, adjustments | Decide whether revenue is gross or net; document it in the KPI definition |
| Ambiguous dates | dd/mm vs mm/dd when both parts are <= 12 | Confirm with the user; Bangladesh, UK and India exports are usually day-first |
| Mixed date formats | Several systems or manual edits in Excel | Normalise to ISO 8601 (`YYYY-MM-DD`) |
| Missing days in a date range | Shop closed, tracking outage, export filtered by status | Ask; for daily metrics, gaps matter (`anomaly-alerts` reports them) |
| Future dates | Wrong year typed, delivery dates mixed with order dates, timezone shifts | Check the lines |
| Case variants | Manual entry (Dhaka / dhaka / DHAKA) | `data-cleaning --case City=title` |
| Leading/trailing or double spaces | Manual entry, copy-paste from WhatsApp or PDFs | Trimmed by `data-cleaning` by default |
| Code columns (leading zeros) | Phone numbers (01711...), postcodes, ids | Keep as text; Excel drops the zero if opened as a number |
| More than 50% null | Optional fields, a column added recently, a broken mapping | Check whether nulls cluster in a date range |
| Constant column | Filter applied at export (e.g. all `paid`) | Fine, but mention it: the file is already filtered |

## Null tokens

Treated as null: empty, `NA`, `N/A`, `null`, `None`, `NaN`, `-`, `--`, `nil`, `#N/A`, `(not set)`.

## Type inference rules

- `code`: digits with a leading zero (`017...`, `0123`), kept as text.
- `integer` / `number`: parses as a number after removing separators, currency, `%` (divided
  by 100), lakh/crore words and Bangla/Devanagari digits.
- `date` / `datetime`: ISO, `dd/mm/yyyy` or `mm/dd/yyyy`, `12 Jan 2026`, `Jan 12, 2026`,
  and `YYYYMMDD` when the column name contains "date" or "day".
- `boolean`: true/false, yes/no. `0`/`1` columns stay `integer`.
- The column type is the majority kind; the rest are reported as mixed or non-parseable.
