## What does this pull request do?

<!-- One or two sentences. Link the issue: "Closes #123". -->

## Type

- [ ] New skill
- [ ] New option, metric or export format in an existing script
- [ ] Workflow / reference improvement
- [ ] Bug fix (wrong number, crash)
- [ ] Repository tooling (validator, CI)

## Checklist

- [ ] `python tools/validate_skills.py` passes
- [ ] `ruff check . && ruff format --check .` passes
- [ ] `pytest` passes; new behaviour has tests with fixtures in `tests/fixtures/`
- [ ] Numbers are checked against a hand calculation or a known reference value in the tests
- [ ] Scripts use only the Python standard library, support `--help`, have `--json` where output is
      structured, and use exit codes 0 / 1 / 2 consistently
- [ ] Scripts are read-only on their input, make no network calls and never print customer identifiers
- [ ] Fixtures are synthetic or fully anonymised (no real names, phones, emails, orders); use example.com
- [ ] New skills: listed in `.claude-plugin/marketplace.json`, the README skills table, `AGENTS.md`,
      the bug report dropdown and CHANGELOG.md
