# Contributing to data-analytics-skills

Thank you for helping! Export formats from real platforms (anonymised), new metrics, fixes,
new skills and clearer docs are all welcome.

- [Ways to contribute](#ways-to-contribute)
- [Good first issues](#good-first-issues)
- [Development setup](#development-setup)
- [Repository layout](#repository-layout)
- [Write a new skill](#write-a-new-skill)
- [Quality bar](#quality-bar)
- [Pull request process](#pull-request-process)

## Ways to contribute

| Size | Idea |
| --- | --- |
| 10 minutes | Fix a typo, clarify a workflow step, add a KPI to the catalog |
| 30 minutes | Add an anonymised header row from a platform export that auto-detection misses |
| 1-2 hours | Add an option or metric to an existing script (see below) |
| Half a day | Write a new skill from the template |

Comment on an issue before you start so nobody else picks the same one.

## Good first issues

Each of these is self-contained and touches one script and its test file.

1. **csv-profiling: Bangla month names.** Parse dates like `৫ জানুয়ারি ২০২৬` (and English
   transliterations) in `parse_date`; copy the change to the other scripts that share it.
2. **csv-profiling: `--sample N`.** Profile only the first N rows (or a reservoir sample) for
   very large files, and print that the result is sampled.
3. **data-cleaning: phone normalisation.** `--phone-cols` that turns `+8801711-000001`,
   `8801711000001` and `01711 000001` into one format (`01711000001`), with tests.
4. **data-cleaning: `--report-csv`.** Write every changed cell (line, column, old, new) to a
   CSV so the user can review changes in a spreadsheet.
5. **kpi-definitions: `--check-csv`.** Check that every input's `source` column exists in a
   given CSV header.
6. **sales-report: discounts and shipping.** Optional `--discount-col` and `--shipping-col`,
   and a gross vs net line in the summary.
7. **sales-report: compare periods.** `--compare previous|last-year` adds a column with the
   change versus the same period last year.
8. **cohort-retention: revenue retention.** `--metric revenue` shows revenue in period N as a
   share of the cohort's period-0 revenue.
9. **ga4-export-analysis: channel grouping.** Map BigQuery source/medium to GA4 default
   channel groups (Organic Search, Paid Social, Email, ...).
10. **ab-test-analysis: exact test for small samples.** Fisher's exact test when any group
    has fewer than 10 conversions, using only `math.comb`.
11. **anomaly-alerts: holiday calendar.** `--holidays FILE` with dates to skip when building
    baselines and to label in the report (Eid, Pohela Boishakh, 11.11).
12. **New skill: `rfm-segmentation`** (see the roadmap in the README).

## Development setup

```bash
git clone https://github.com/saizul/data-analytics-skills.git
cd data-analytics-skills
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

python tools/validate_skills.py   # SKILL.md frontmatter, sections, links, marketplace listing
ruff check . && ruff format --check .
pytest
```

To try your changes in Claude Code, either copy a skill to `~/.claude/skills/` or add your
checkout as a local marketplace:

```bash
claude plugin marketplace add ./data-analytics-skills
claude plugin install data-analytics-skills@data-analytics-skills
```

For Codex, copy the skill folder to `~/.agents/skills/`.

## Repository layout

```
.claude-plugin/
  marketplace.json      marketplace + plugin entry listing every skill
  plugin.json           plugin manifest (name, version, author)
skills/<name>/
  SKILL.md              frontmatter + workflow (the part agents read)
  scripts/*.py          standalone helpers, Python 3.8+ stdlib only
  references/*.md       detail loaded on demand
  assets/               templates (kpis.example.yaml)
templates/skill/        copy this to start a new skill
tests/
  test_<skill>.py       one test module per skill
  fixtures/             synthetic CSV/JSON/YAML inputs
tools/validate_skills.py
```

## Write a new skill

1. Open a "New skill proposal" issue first so we can agree on scope.
2. Copy the template:
   ```bash
   cp -r templates/skill skills/rfm-segmentation
   mv skills/rfm-segmentation/scripts/your_script.py skills/rfm-segmentation/scripts/rfm.py
   ```
3. Edit `SKILL.md`:
   - `name` equals the folder name: lowercase letters, digits, single hyphens, max 64 chars.
   - `description` (max 1024 chars) says **what** it does with concrete keywords and **when**
     to use it, starting the second part with "Use when ...". This text decides whether
     the agent picks the skill, so list the phrases and file types users actually mention.
   - Required sections: `## When to use`, `## When not to use`, `## Workflow`, `## Output`.
   - Workflow steps are imperative and numbered, with exact commands, the questions to ask
     the user (definitions, date order, which rows count) and decision points.
   - Keep it under 400 lines; move definitions and platform notes to `references/`.
4. Write the script: `argparse` with a useful `--help`, `--json` output, exit codes
   0 (ok) / 1 (findings) / 2 (error), read-only on inputs, no network, no customer
   identifiers in the output. Copy `parse_number`, `parse_date` and `read_table` from an
   existing script so Bangla digits, lakh/crore and day-first dates work the same everywhere.
5. Add `tests/test_rfm_segmentation.py` with small synthetic fixtures whose results you
   can calculate by hand. Cover edge cases (empty file, missing columns, ties) and the CLI.
6. Add the skill to `.claude-plugin/marketplace.json` (`plugins[0].skills`), the README
   skills table, the table in `AGENTS.md`, the bug report dropdown and `CHANGELOG.md`
   under "Unreleased".
7. Run the validator, ruff and pytest.

## Quality bar

- **Correct numbers.** Every formula has a test against a hand calculation or a published
  reference value. State definitions (gross vs net, which statuses count) in the output.
- **Real exports.** Column detection and parsing must match real platform exports; add an
  anonymised fixture when you add a format.
- **Honest output.** Partial periods, excluded rows, small samples and data-quality problems
  are reported, never hidden.
- **Privacy.** Reports show aggregates. Fixtures are synthetic: fake names, example.com
  emails, made-up phone numbers.
- **Deterministic where it matters.** If a step is "compute X from this file", write a
  script and test it instead of relying on the model reading a large CSV.

## Pull request process

1. Fork, create a branch, make focused commits.
2. Make sure CI passes locally (validator, ruff, pytest).
3. Fill in the pull request template.
4. A maintainer reviews within a few days. Small, focused pull requests are merged fastest.

By contributing you agree that your contributions are licensed under the MIT License.
