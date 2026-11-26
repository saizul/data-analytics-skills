# GA4 exports: what the script reads

## UI report CSV

Downloaded with "Share this report" > "Download File" > "Download CSV". The file starts with
`#` comment lines (report name, account, property, `# Start date: YYYYMMDD`, `# End date: YYYYMMDD`),
then one or more tables separated by blank or comment lines. Numbers may contain thousands
separators; rates are fractions (`0.61`) or percentages (`61.2%`).

The script:

- reads every table; the columns that are mostly numeric are metrics, the rest dimensions
  (Date, Week, Month, Hour columns are always dimensions);
- skips `Grand total` / `Total` rows and rows with an empty dimension;
- totals additive metrics (Sessions, Engaged sessions, Event count, Key events, Views,
  Transactions, Total revenue, New users) and never totals Total users, rates, averages or
  "per session" columns;
- recomputes engagement rate (engaged sessions / sessions), key events per session and
  revenue per session from the totals;
- sorts by Sessions (or the first additive metric) and shows each row's share; Date tables
  are shown as a sorted trend with the highest and lowest day.

Recognised metric names: Sessions; Total users, Users, Active users; New users; Engaged
sessions; Key events, Key events (event_name), Conversions; Total revenue, Purchase revenue;
Views; Event count; Transactions, Ecommerce purchases.

## BigQuery export (events_YYYYMMDD tables)

Export a query result as newline-delimited JSON (`bq query --format=json` gives an array; the
console "Save results > JSON (local file)" gives NDJSON). Both work. Fields used:

| Field | Use |
| --- | --- |
| `user_pseudo_id` | users; part of the session key |
| `event_params[key=ga_session_id]` | session key (events without it are counted but not sessionised) |
| `event_timestamp` | ordering within a session (micros) |
| `event_date` | session date (date of the first event) |
| `event_name` | page views (`page_view`), conversions (`--conversion-events`, default `purchase`) |
| `event_params[key=page_location]` | landing page from the first `page_view` or `session_start` (path only unless `--keep-query`) |
| `event_params[key=session_engaged]` | `"1"` marks an engaged session |
| `session_traffic_source_last_click.manual_campaign.source/medium` | session source/medium (newest exports) |
| `collected_traffic_source.manual_source/manual_medium`, `gclid` | fallback source/medium (`gclid` = google / cpc) |
| `event_params[key=source/medium]` | fallback source/medium |
| `ecommerce.purchase_revenue`, `event_value_in_usd`, `event_params[key=value]` | revenue of `purchase` events (first one present) |
| `device.category` | device breakdown |

`traffic_source.*` is the user's first-touch source and is deliberately not used for sessions.
Sessions without any source information are `(direct) / (none)`.

## Differences from the GA4 UI

- The UI applies thresholds, sampling, modelled conversions (consent mode) and its own
  attribution; BigQuery numbers are raw and usually a few percent different.
- The UI counts key events; this script also gives converting sessions for BigQuery input.
- Timezone: `event_date` is in the property timezone; `event_timestamp` is UTC.

## Example BigQuery query for a small sample

```sql
SELECT event_date, event_timestamp, event_name, user_pseudo_id, event_params,
       collected_traffic_source, session_traffic_source_last_click, ecommerce,
       event_value_in_usd, device
FROM `project.analytics_123456.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20261001' AND '20261007'
```
