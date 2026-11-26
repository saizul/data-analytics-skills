# AGENTS.md

Guidance for Codex CLI and other coding agents that use or work on this repository.

## Using the skills

The skills live in `skills/<name>/SKILL.md` and follow the Agent Skills format. Codex
discovers them when they are copied to `~/.agents/skills/` or `.agents/skills/` (see
README "Install"). If you are reading this file inside the repository instead:

1. Pick the skill whose `description` matches the user's request:

   | Request is about | Skill |
   | --- | --- |
   | what is in a CSV, data quality, outliers, duplicates, date ranges | `csv-profiling` |
   | cleaning, dedupe, Bangla digits, lakh/crore amounts, mixed dates | `data-cleaning` |
   | defining metrics, KPI dictionary, "what does revenue mean here" | `kpi-definitions` |
   | retention, cohorts, repeat purchases over time, LTV curves | `cohort-retention` |
   | sales summary, revenue trend, AOV, top products, repeat rate | `sales-report` |
   | GA4 exports, traffic sources, landing pages, conversions, BigQuery events | `ga4-export-analysis` |
   | A/B test significance, lift, sample size, test duration, SRM | `ab-test-analysis` |
   | unusual days, spikes, drops, daily metric alerts | `anomaly-alerts` |

   Most analyses start with `csv-profiling`, then `data-cleaning` if needed.
2. Read that `SKILL.md` completely and follow its Workflow section in order.
3. Paths such as `scripts/x.py`, `references/y.md` and `assets/z.yaml` are relative to the
   skill folder. `${CLAUDE_SKILL_DIR}` in the text means that folder; Codex does not expand it.
4. Read files in `references/` only when a workflow step points to them.

## Safety rules (apply to every skill)

- The scripts only read their input. `clean_csv.py` writes only with `--out` and never over
  the input. Do not edit or overwrite the user's original export.
- Exports contain personal data (names, phones, emails, addresses). Quote only aggregates
  and the few rows needed to explain a problem; never paste whole files into the chat, commit
  them, or send them anywhere.
- No network access is needed. Do not upload data to online tools or APIs unless the user
  explicitly asks.
- Do not invent numbers, definitions, owners or targets. If a definition (which statuses count,
  gross vs net) is unclear, ask, and state the assumption in the report.
- Report caveats the scripts print (excluded rows, partial periods, sample ratio mismatch).

## Working on this repository

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python tools/validate_skills.py   # frontmatter, sections, links, marketplace listing
ruff check . && ruff format --check .
pytest
```

- Scripts: Python 3.8+ standard library only, `#!/usr/bin/env python3`, `argparse` with
  `--help`, `--json` where output is structured, exit 0/1/2 (ok / findings / error).
- Scripts must stay standalone (one file each, no shared module) so a single skill folder
  can be copied on its own. The number/date parsing helpers are intentionally duplicated;
  change them in every script and keep the tests in `tests/test_csv_profiling.py` passing.
- Every script needs tests in `tests/test_<skill_with_underscores>.py` with fixtures in
  `tests/fixtures/`. Fixtures are synthetic; use example.com addresses and fake ids.
- Keep each `SKILL.md` under 400 lines; move detail to `references/`.
- A new skill must be added to `.claude-plugin/marketplace.json` (`plugins[0].skills`), the
  README table, the table above, the bug report dropdown and `CHANGELOG.md`. The validator
  enforces the manifest.
