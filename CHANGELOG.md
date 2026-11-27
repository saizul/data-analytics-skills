# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `ab-test-analysis`: `ab_test.py sample-size --split 90,10` plans unequal traffic splits
  (control first, any number of groups). It prints visitors per group, the total, the
  duration, and the total an equal split would need; JSON adds `split`,
  `per_group_by_split` and `total_with_equal_split`. `sample_size()` takes a `ratio`.

## [0.1.0] - 2026-11-26

### Added

- `csv-profiling`: `profile_csv.py` with type inference (integer, number, date, datetime,
  boolean, leading-zero codes, string), nulls, uniques and candidate keys, numeric stats, IQR
  outliers with line numbers, date ranges with missing and future days, ambiguous day/month
  dates, mixed formats, duplicate and ragged rows, whitespace and case variants.
- `data-cleaning`: `clean_csv.py` (dry run by default) for trimming, null tokens, Bangla and
  Devanagari digits, lakh/crore and western grouping, currency symbols, accounting negatives,
  lakh/crore words, percentages, ISO 8601 dates, case normalisation, snake_case headers and
  exact or key-based deduplication.
- `kpi-definitions`: `validate_kpis.py` with a safe YAML subset parser, formula parser,
  checks for required fields, units, grains, directions, owners, unknown names and functions,
  cycles, zero-division rules and grain mismatches; Markdown metric dictionary; KPI template
  and catalog.
- `cohort-retention`: `cohort_retention.py` for monthly and weekly cohorts, partial-period
  handling, size-weighted averages, cumulative revenue per user; Markdown, CSV and JSON output.
- `sales-report`: `sales_report.py` for revenue, orders, AOV, units, customers, repeat rate,
  day/week/month trends with new vs returning customers, top products, status filters,
  Shopify-style line-item exports and South Asian number formatting.
- `ga4-export-analysis`: `ga4_summary.py` for GA4 report CSVs (multiple tables, comment
  headers, recomputed rates) and BigQuery export events (sessions, engagement, landing pages,
  source/medium, devices, conversions, revenue).
- `ab-test-analysis`: `ab_test.py` with two-proportion z-test, confidence intervals,
  Bonferroni correction, sample ratio mismatch check, sample size and duration planning.
- `anomaly-alerts`: `detect_anomalies.py` with rolling median and MAD robust z-scores,
  weekly seasonality, missing-day detection, direction and minimum-change filters, alert lines
  and exit codes for cron and CI.
- Claude Code plugin marketplace manifest, `tools/validate_skills.py`, CI and release workflows.

[Unreleased]: https://github.com/saizul/data-analytics-skills/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/saizul/data-analytics-skills/releases/tag/v0.1.0
