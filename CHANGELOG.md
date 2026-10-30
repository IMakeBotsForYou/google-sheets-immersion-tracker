# Changelog

## 1.0.0

First modular release (previously a single `main.py`).

- Split into the `immersion_tracker` package: settings, credentials, calendar logic, chat parsing, report
  parsing, planning, and a `sheets` subpackage (week tables, log tab, charts).
- Secrets and environment values moved out of the code: `.env` (spreadsheet id, key location) and
  `credentials/`. Tunable behaviour moved to `config.toml`; people to `people.json`. All git-ignored.
- Students are listed in the order of the sheet's columns, read from the sheet on every run.
- Two line charts (hours of immersion, new Anki cards) on the log tab, one stable colour per student.
- New flags: `--offline`, `--config`, `--people`, `--no-pause`, `--version`.
- Test suite (unit + end-to-end on a fake Google Sheet) and CI.
