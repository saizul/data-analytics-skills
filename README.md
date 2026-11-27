# data-analytics-skills

[![CI](https://github.com/saizul/data-analytics-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/data-analytics-skills/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/saizul/data-analytics-skills?sort=semver)](https://github.com/saizul/data-analytics-skills/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/saizul/data-analytics-skills?style=social)](https://github.com/saizul/data-analytics-skills/stargazers)

**Agent Skills that turn Claude Code and Codex into a careful data analyst for your CSV exports - sales, cohorts, GA4, A/B tests and alerts, with tested scripts instead of guessed numbers. No BI tool needed.**

Small businesses and product teams live in exports: Shopify or WooCommerce orders, Daraz
and POS files, Google Sheets, GA4 downloads, BigQuery samples. These eight skills give your
coding agent a repeatable workflow for each analytics job, and a standard-library Python
script that computes the numbers exactly, offline, on your machine.

- **Exact numbers.** Totals, retention, p-values and sample sizes come from tested code, not
  from a model reading a spreadsheet. 160+ tests check results against hand calculations and
  published reference values (for example 31,234 visitors per group for 5% baseline, +10% lift).
- **Messy real-world exports.** Bangla digits (`২,৫০০`), lakh/crore grouping (`1,00,000`),
  `Tk`/`BDT`/`৳`, `(300)` negatives, day-first dates, line-item vs order-level files,
  GA4 comment headers and `Grand total` rows.
- **Safe by default.** Read-only on inputs, no network calls, no telemetry, cleaning is a dry
  run until you pass `--out`. Sales, cohort, GA4 and A/B reports show aggregates only;
  profiling shows example values to locate problems, or hides them with `--redact`.
- **Pipeline friendly.** Every script has `--help`, `--json` and meaningful exit codes, so the
  same checks run in cron or CI.

## Skills

| Skill | What it does | Try asking |
| --- | --- | --- |
| [csv-profiling](skills/csv-profiling/SKILL.md) | Types, nulls, uniques and keys, min/median/max, IQR outliers with line numbers, date ranges and gaps, duplicates, ragged rows, case and whitespace issues | "What's in this orders.csv, and can I trust it?" |
| [data-cleaning](skills/data-cleaning/SKILL.md) | Dry-run cleaning: trim, null tokens, Bangla digits, lakh/crore and currency amounts, ISO dates, case fixes, snake_case headers, exact or key-based dedupe | "Clean this export: the amounts don't add up and dates are mixed" |
| [kpi-definitions](skills/kpi-definitions/SKILL.md) | KPI dictionary template; validator for formula, unit, grain, owner, direction, unknown names, cycles, division rules; Markdown metric dictionary | "Help us define AOV, repeat rate and net revenue properly" |
| [cohort-retention](skills/cohort-retention/SKILL.md) | Monthly/weekly cohorts, retention by period with partial periods marked, weighted averages, cumulative revenue per customer (LTV) | "Do customers who first bought in January come back?" |
| [sales-report](skills/sales-report/SKILL.md) | Revenue, orders, AOV, units, customers, repeat rate, daily/weekly/monthly trend with new vs returning, top products, Markdown output | "Write the October sales report from this Shopify export" |
| [ga4-export-analysis](skills/ga4-export-analysis/SKILL.md) | GA4 report CSVs and BigQuery event JSON: sessions, engagement, conversions and revenue by source/medium, landing page, device, date | "Which channels and landing pages actually convert?" |
| [ab-test-analysis](skills/ab-test-analysis/SKILL.md) | Lift, two-proportion z-test p-value, confidence interval, Bonferroni, sample ratio mismatch check, sample size and test duration (equal or unequal splits) | "Variant B: 5.8% vs 5.0%. Did it win? How long should the next test run?" |
| [anomaly-alerts](skills/anomaly-alerts/SKILL.md) | Rolling median + MAD robust z-scores, weekday seasonality, missing days, one-line alerts and exit codes for cron/CI | "Revenue fell yesterday. Is that unusual?" |

## Install

### Claude Code: plugin marketplace (recommended)

```text
/plugin marketplace add saizul/data-analytics-skills
/plugin install data-analytics-skills@data-analytics-skills
```

Or from your shell:

```bash
claude plugin marketplace add saizul/data-analytics-skills
claude plugin install data-analytics-skills@data-analytics-skills
```

Plugin skills are namespaced, e.g. `/data-analytics-skills:sales-report`. Claude also picks
them up automatically when your request matches a skill's description. Update later with
`/plugin marketplace update data-analytics-skills`.

### Claude Code: copy the skills

```bash
git clone https://github.com/saizul/data-analytics-skills.git
# all projects (personal skills)
mkdir -p ~/.claude/skills && cp -r data-analytics-skills/skills/* ~/.claude/skills/
# or just one project
mkdir -p .claude/skills && cp -r data-analytics-skills/skills/sales-report .claude/skills/
```

Each release also has one zip per skill and an all-skills zip under
[Releases](https://github.com/saizul/data-analytics-skills/releases).

### Codex CLI

Codex reads skills from `~/.agents/skills` (all repositories) and `.agents/skills` in a
repository (from the current directory up to the repository root):

```bash
git clone https://github.com/saizul/data-analytics-skills.git
mkdir -p ~/.agents/skills && cp -r data-analytics-skills/skills/* ~/.agents/skills/
# or per repository
mkdir -p .agents/skills && cp -r data-analytics-skills/skills/csv-profiling .agents/skills/
```

Codex also ships a `$skill-installer` skill that can install skills from a GitHub
repository; ask it to install from `saizul/data-analytics-skills`. Skill locations and the
installer are described in the [Codex skills documentation](https://developers.openai.com/codex/skills);
check it if your Codex version behaves differently. [AGENTS.md](AGENTS.md) explains how
Codex and other agents should use these skills.

### Any other agent

The skills follow the open [Agent Skills format](https://agentskills.io/specification):
a folder with `SKILL.md` (YAML frontmatter + instructions), `scripts/`, `references/` and
`assets/`. Point your agent at the folder, or run the scripts yourself; every script has `--help`.

## Usage examples

```text
> Here's orders_export.csv from Shopify. How did October go?
  (Profiles the file, notices it is one row per line item with the status only on the first
   line, runs sales_report.py with the Lineitem columns, compares with September and writes
   a five-line summary with the top products and the repeat rate.)

> Our retention feels worse since the Eid campaign. Can you check?
  (Builds monthly cohorts with cohort_retention.py, shows the campaign cohort's M1 at 9% vs
   18% for the others, and explains that the campaign brought one-time buyers.)

> We ran the new checkout for two weeks: 10,000 vs 9,000 visitors, 500 vs 520 orders.
  (ab_test.py reports a sample ratio mismatch on a planned 50/50 split and refuses to call a
   winner until the assignment bug is found.)
```

Run the scripts directly too:

```bash
python3 skills/csv-profiling/scripts/profile_csv.py orders.csv
python3 skills/data-cleaning/scripts/clean_csv.py orders.csv --case City=title --out orders.clean.csv
python3 skills/kpi-definitions/scripts/validate_kpis.py kpis.yaml --markdown > METRICS.md
python3 skills/cohort-retention/scripts/cohort_retention.py orders.csv --value-col total --currency BDT
python3 skills/sales-report/scripts/sales_report.py orders.csv --period week --currency BDT --lakh
python3 skills/ga4-export-analysis/scripts/ga4_summary.py traffic_acquisition.csv
python3 skills/ab-test-analysis/scripts/ab_test.py sample-size --baseline 0.04 --mde 0.1 --daily-traffic 2500
python3 skills/anomaly-alerts/scripts/detect_anomalies.py daily.csv --seasonal weekly --last 1 --format alert
```

## How skills work

At startup the agent loads only each skill's `name` and `description` (about 100 tokens
each). When your request matches a description, it reads that skill's `SKILL.md`: the
workflow, the questions to ask you, decision points and what to report. Longer material
lives in `references/` and is read only when a step needs it; `assets/` holds templates
(a KPI dictionary). Scripts run as normal commands, so their output is exact and repeatable.

```
skills/<skill-name>/
  SKILL.md          frontmatter (name, description) + workflow
  scripts/          standalone Python 3 helpers (stdlib only, --help, --json)
  references/       definitions, platform export formats, interpretation guides
  assets/           templates to copy (kpis.example.yaml)
```

## FAQ

**Does my data leave my machine?**
The scripts make no network calls and send nothing anywhere. Your agent reads their output,
so anything in the output reaches the model provider you use. Reports show aggregates and do
not print customer names, emails or phone numbers; `csv-profiling` and `data-cleaning` quote
example values with line numbers so you can fix them (`profile_csv.py --redact` hides text values).

**Do I need pandas, Jupyter or a BI tool?**
No. Python 3.8+ is enough; every script uses only the standard library and is one file, so a
single skill folder can be copied on its own.

**How big can the files be?**
The scripts read the file into memory; a few hundred thousand rows are fine on a laptop. For
larger exports, aggregate first (or profile a sample).

**My export has columns the scripts do not recognise.**
Every script auto-detects common names and accepts `--*-col` overrides. Platform notes for
Shopify, WooCommerce, Daraz and Google Sheets are in the sales-report references. Please open
an issue with an anonymised header row so detection can be improved.

**Is the GA4 analysis the same as the GA4 interface?**
Close, not identical: the UI applies thresholds, modelled data and its own attribution. The
skill explains the differences.

## Roadmap

Ideas for new skills (great first contributions; see [CONTRIBUTING.md](CONTRIBUTING.md)):

- `rfm-segmentation` - recency/frequency/monetary scores and segments from orders
- `revenue-ab-test` - revenue per visitor and AOV tests with Welch's t-test or bootstrap
- `funnel-analysis` - step conversion and drop-off from event exports
- `forecasting-basics` - seasonal naive and moving-average forecasts with error metrics
- `marketing-attribution` - first/last/linear touch from UTM-tagged order exports
- `inventory-reorder` - sales velocity, days of stock and reorder points from POS exports
- `survey-analysis` - Likert summaries, NPS and open-text coding from form exports
- `subscription-metrics` - MRR movements, churn and LTV from subscription exports

## Contributing

Contributions are welcome: export formats from real platforms (anonymised), new metrics,
fixes, new skills and clearer docs. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the skill
template, the quality bar and how to run the validator and tests:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python tools/validate_skills.py && ruff check . && ruff format --check . && pytest
```

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) and report security issues
privately as described in [SECURITY.md](SECURITY.md).

Google Analytics, Shopify, WooCommerce and Daraz are trademarks of their owners. This
project is independent and not affiliated with them.

## License

[MIT](LICENSE) (c) Saizul Amin
