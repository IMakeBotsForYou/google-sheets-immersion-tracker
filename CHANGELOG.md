# Changelog

## Unreleased

- **Late reports now count.** A report that arrives after its day was already closed with ✖ used to be ignored
  by the add-only rules: the cell stayed ✖ and the charts kept showing 0. Now, when the chat has a report for a
  day the sheet holds as "nothing":
  - the week table's **✖ is replaced by the ◯ count**;
  - the **chart data** is filled in for that day, and the running totals after it are raised by the same amount;
  - the run prints a **warning** for each (`late report(s) counted ...`); a dry run says what *would* be counted.

  Everything else stays add-only: a ◯ cell, a log row, or a number in the chart data that someone corrected by
  hand is still never replaced (only a cross, or a day the chart data holds as 0 hours / 0 cards while the log
  has a report for it, counts as "nothing"). Once counted, the day is no longer "nothing", so it happens once.
- Test: free text after a report ("...I'll finish Anki and read later") does not stop the report counting.

## 1.2.1

- Warnings name the student as in the sheet (the `people.json` name) instead of the WhatsApp sender, so a
  phone number is shown as "Noam". Senders not saved yet are still shown as they appear in the chat.

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
