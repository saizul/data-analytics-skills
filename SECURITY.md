# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## What counts as a vulnerability

These skills are run by AI agents on business data that often contains personal
information, so unsafe behaviour is treated like a code vulnerability:

- A script that prints customer identifiers (names, emails, phone numbers, addresses) in a
  report where only aggregates are expected
- A script that writes outside the output path it was given, overwrites its input, or makes
  network calls
- Code execution or resource exhaustion from crafted input (CSV, JSON, YAML), for example a
  KPI file that makes the parser execute code
- A `SKILL.md` workflow that tells the agent to upload data, commit exports, delete files or
  change source systems without asking the user first
- Statistical guidance that is wrong in a way that leads to confidently wrong decisions,
  e.g. a p-value or sample size formula error

A wrong number in an edge case that is clearly visible is a normal bug: please open an issue.

## Reporting

Please **do not** open a public issue. Use
[GitHub private vulnerability reporting](https://github.com/saizul/data-analytics-skills/security/advisories/new)
with the affected skill, version, impact and steps to reproduce. Use synthetic data in
examples, never real customer exports.

You will get an answer within 5 working days. Fixes are released as soon as possible and
credited in the changelog unless you prefer otherwise.
