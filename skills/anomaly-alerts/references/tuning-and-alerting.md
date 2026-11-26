# Tuning and alerting

## How the score works

For each day `t` with a value `x`:

1. Baseline = values of the previous `--window` days (or the same weekday in the previous
   `--window` weeks with `--seasonal weekly`). Days without data are skipped.
2. If fewer than `--min-periods` baseline values exist, the day is not scored.
3. `median` of the baseline and `MAD = median(|baseline - median|)`.
4. Robust z = `(x - median) / (MAD / 0.6745)`. When MAD is 0 (flat history), the mean
   absolute deviation is used; if that is 0 too, any change is infinite z.
5. Anomaly if `|z| >= --threshold` and `|x - median| / |median| >= --min-change` and
   `|x - median| >= --min-abs`, filtered by `--direction`.
6. Dates between the first and last date with no row are reported as `missing`
   (`--ignore-missing` to hide).

## Tuning

| Symptom | Change |
| --- | --- |
| Every weekend flagged | `--seasonal weekly` |
| Small shops: 2 vs 4 orders flagged as -50% | `--min-abs 3` (orders) or `--min-abs 5000` (revenue) |
| Too many alerts | `--threshold 4` or `--min-change 0.3` |
| Real drops missed | `--threshold 3`, shorter `--window 7` for fast-changing businesses |
| Only drops matter (revenue, sessions) | `--direction down` |
| New product launch shifts the level | Expect alerts for a few days until the window catches up |

Known calendar effects in Bangladesh worth annotating: Eid-ul-Fitr and Eid-ul-Adha (sales
peak before, drop during the holidays), Pohela Boishakh, 11.11 and 12.12 campaigns,
Black Friday for export-oriented shops, Ramadan evening shifts, and hartal or internet outages.

## Daily alert with cron

```bash
# 09:00 every day: check yesterday; print a line and run your own notifier only if unusual
0 9 * * * cd /srv/reports && python3 detect_anomalies.py daily.csv --last 1 --format alert \
  --seasonal weekly > /tmp/anomaly.txt || your-notify-command < /tmp/anomaly.txt
```

Exit code 1 means anomalies were found, so `||` runs the notifier. Keep webhook URLs and
tokens in environment variables or a secret store, never in the CSV folder or the repository.

## GitHub Actions (scheduled)

```yaml
on:
  schedule: [{cron: "0 3 * * *"}]   # 09:00 Asia/Dhaka
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 skills/anomaly-alerts/scripts/detect_anomalies.py data/daily.csv --last 1 --format alert
```

A failing run sends the repository's normal failure notification; no secrets needed.
