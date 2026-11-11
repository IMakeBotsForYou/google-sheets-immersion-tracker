# Changelog

## 1.4.0

- **Late reports fill in crossed-out days.** A ✖ is replaced by circles when the chat now has a report for that day
  (main tab and conjugations tab). Circles already in a cell are never replaced; if the chat disagrees with them a
  `WARNING` names the student and day and the cell is left alone (silent if both agree). `--overwrite` still
  replaces everything, and `--dry-run` previews what would be filled in. New `appearance.cross_marks` setting.
- **Log tab: new `הטיות` column** between `אנקי` and the total (the total never includes conjugations or Anki).
  A log from an earlier version is upgraded in place, including one that has an empty header cell where the
  column goes; empty `הטיות` cells of existing rows are filled from the chat, nothing else is replaced.
- A follow-up message containing only an Anki / conjugations line no longer replaces the day's full report
  (it used to be able to zero the day); it only supplies the missing numbers.
- Late log rows are counted and the run suggests `--rebuild-charts`.
- The charts moved one column to the right to stay clear of the wider log table.

## 1.3.0

- **Conjugations:** a report may contain an optional `הטיות 40` line (no unit needed). It is written to its own
  tab (`הטיות`, tables named `הטיות שבוע 3`, `הטיות שבוע 4`, ... from week 3), one ◯ per 20 exercises, a ✖ below
  that. Same layout and student columns as the main tab; add-only; skipped quietly if the tab is missing or
  nobody uses the line. New `[conjugations]` settings.
- **Free text inside a report** is ignored, and now produces a warning (naming the student) when it contains a
  number or mentions an activity: a typo in an activity name can no longer silently cost a circle.
- An absurd day number (such as `יום 29013890321890231890231`) used to crash the run with `OverflowError`; it is
  now ignored with a warning and the day the message was sent is used.
- When the add-only log keeps a row that disagrees with the chat, the run lists which rows
  (`2026-10-27 Alice: the sheet has 275 min; the chat says ...`).
- Every tab the tool writes to must now have its own name (validated), and the table-name regexes are validated.

## 1.2.1

- Warnings name the student as in the sheet (the `people.json` name) instead of the WhatsApp sender, so a
  phone number is shown as "Nora". Senders not saved yet are still shown as they appear in the chat.

## 1.2.0

- The **log tab is now add-only** too: a (date, student) row that is already there is kept as it is, so values
  corrected by hand stay corrected. New rows are still added. The run says how many existing rows differ from
  the chat. `--overwrite` replaces rows with the chat's version.
- Running totals in the chart data **continue from the numbers the tab holds**. Before, new days were taken from
  the log's own running total, so a hand-corrected total was followed by a jump back to the uncorrected one.
  Untouched numbers are still exactly what the log gives.
- New `--rebuild-charts`: rebuild only the chart data tab from the log, leaving the log alone.
- README: a "Where is my data stored?" section.

## 1.1.0

- The chart data tab is now add-only, like the ◯ / ✖ cells: filled cells are never replaced, only empty ones
  (new days, new students) are filled. `--overwrite` (or `overwrite_filled_cells = true`) rebuilds it from the log.
- Days and students already in the tab are kept, even if they are no longer in the log / `people.json`.
- Switching `hours_cumulative` / `cards_cumulative` rebuilds just that block (the tab records which mode it was
  written in), so running totals and per-day values are never mixed.

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
