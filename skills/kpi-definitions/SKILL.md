---
name: kpi-definitions
description: Write and validate a KPI dictionary (metric definitions) in YAML or JSON - each KPI with id, name, description, formula, unit, grain, owner and direction, built from declared inputs with source and aggregation. The validator parses every formula, finds unknown names and functions, circular definitions, divisions without a zero_division rule, placeholder owners, invalid grains/units, unused inputs and coarser-grain dependencies, and renders a Markdown metric dictionary. Use when the user wants to define KPIs or metrics, agree on what "revenue", "AOV", "conversion rate" or "active customer" mean, document a dashboard's numbers, or review an existing metrics file.
license: MIT
compatibility: Python 3.8+ standard library only. YAML is parsed with a built-in safe subset parser (no PyYAML needed, nothing executed).
metadata:
  author: Saizul Amin
  version: "0.1.0"
---

# KPI definitions

Numbers only mean something when everyone computes them the same way. A KPI dictionary
pins down the formula, the unit, the grain (per order, per day, per month), the owner who
answers questions about it, and which direction is good.

Paths below are relative to this skill's folder (in Claude Code: `${CLAUDE_SKILL_DIR}`).

## When to use

- "Define our KPIs", "write a metric dictionary", "what should we track"
- Two reports show different revenue or conversion numbers
- Before building a dashboard or a recurring `sales-report`
- Reviewing an existing `kpis.yaml` / `metrics.json` in a repository

## When not to use

- Computing the numbers: `sales-report`, `cohort-retention`, `ga4-export-analysis`
- Writing SQL or dbt semantic models: the dictionary is the spec they implement

## Workflow

1. **Start from the template** unless the user already has a file:
   ```bash
   python3 scripts/validate_kpis.py --template > kpis.yaml
   ```
   The same starter is in [assets/kpis.example.yaml](assets/kpis.example.yaml).
2. **Interview, do not invent.** For each KPI ask: what decision does it drive, which rows
   count (paid? delivered? excluding refunds?), the grain, the owner (a named person or
   team), and whether up is good. Use [references/kpi-catalog.md](references/kpi-catalog.md)
   for standard small-business and product definitions and their common traps.
3. **Write inputs first** (`inputs:` = base measures with `source` and `aggregation`), then
   KPIs whose `formula` uses only input ids, other KPI ids, numbers, `+ - * / %`,
   parentheses and the functions `sum count count_distinct avg min max abs round coalesce nullif`.
4. **Validate** and fix every error; resolve or consciously accept warnings:
   ```bash
   python3 scripts/validate_kpis.py kpis.yaml
   python3 scripts/validate_kpis.py kpis.yaml --strict      # warnings fail too (CI)
   python3 scripts/validate_kpis.py kpis.json --json
   ```
   Decision points:
   - `formula divides`: add `zero_division: null` (show "-") or `zero_division: 0`.
   - `owner is a placeholder`: the KPI is not ready; ask who owns it.
   - `coarser grain`: a monthly KPI inside a daily KPI usually means a wrong definition.
5. **Publish the dictionary** for the team:
   ```bash
   python3 scripts/validate_kpis.py kpis.yaml --markdown > METRICS.md
   ```
6. **Keep it in git** next to the reports; change a definition only with the owner's
   agreement and note the date, since historical numbers change with it.

## Output

The validator report, then (with `--markdown`) a table:

```markdown
| KPI | Definition | Formula | Unit | Grain | Owner | Direction |
| --- | --- | --- | --- | --- | --- | --- |
| **Average order value** (`aov`) | Net revenue per paid order | `net_revenue / orders` | currency (BDT) | month | Growth team | up |
```

When reviewing someone's file, list errors first (they make numbers wrong or undefined),
then warnings, then suggested definitions for missing standard KPIs.
