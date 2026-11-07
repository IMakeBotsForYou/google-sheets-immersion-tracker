"""The log tab: one row per (day, student) with the activity breakdown.

It is also the memory of the tool: every run adds its new rows to what is already there, so history
survives even if a later chat export no longer contains the old messages.  The charts are built from it.

Add-only, like the circles in the week tables: a (date, student) row that is already in the tab is never
replaced - so a value corrected by hand stays corrected.  ``overwrite`` replaces rows with what the chat says.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Mapping, Sequence

from ..console import print_table
from ..reports import DayTotals

LEGACY_LOG_COLUMN_NAMES = {"יוטיוב": "צפייה"}      # old header text -> current one, so old logs are still recognised


def log_columns(activities: Sequence[str]) -> list[str]:
    """Header of the log tab: date, day number, student, one column per activity, Anki, total minutes."""
    return ["תאריך", "יום", "תלמיד"] + list(activities) + ["אנקי", "סך הכל (דקות)"]


def build_log_rows(day_totals: Mapping[tuple[str, date], DayTotals], day1: date, columns: Sequence[str],
                   activities: Sequence[str]) -> list[list]:
    """Rows sorted by date, then by the students' order in the sheet (`columns`)."""
    column_order = {name: i for i, name in enumerate(columns)}
    rows = []
    for (column, day), totals in sorted(day_totals.items(),
                                        key=lambda item: (item[0][1], column_order.get(item[0][0], 99))):
        rows.append([day.isoformat(), (day - day1).days + 1, column]
                    + [totals.minutes_by_activity.get(activity, "") for activity in activities]
                    + ["" if totals.anki_cards is None else totals.anki_cards]
                    + [totals.total_minutes])
    return rows


def print_log(rows: list[list], title: str, header: Sequence[str]) -> None:
    print(f"\n=== {title} ({len(rows)} rows) ===")
    print_table(list(header), rows)


def print_last_day_per_student(rows: list[list], columns: Sequence[str], header: Sequence[str]) -> None:
    """Instead of the whole log: each student's final day from this run - total minutes, Anki cards in brackets."""
    column_order = {name: i for i, name in enumerate(columns)}
    last_row: dict[str, list] = {}
    for row in rows:
        if row[2] not in last_row or row[0] >= last_row[row[2]][0]:
            last_row[row[2]] = row
    table = []
    for row in sorted(last_row.values(), key=lambda r: (column_order.get(r[2], 99), r[2])):
        anki = row[-2]
        table.append([row[0], row[1], row[2], f"{row[-1]}" if anki == "" else f"{row[-1]} ({anki})"])
    print("\nLast day added per student:")
    print_table([header[0], header[1], header[2], f"{header[-1]} ({header[-2]})"], table)


def write_log(spreadsheet, rows: list[list], title: str, columns: Sequence[str], header: Sequence[str],
              overwrite: bool = False):
    """Add this run's rows to the log tab.  A row for a (date, student) that is already there is kept as it is,
    unless `overwrite` (then it is replaced by the chat's version).
    Returns (log worksheet, all rows now in the log), or None if the tab was left alone."""
    import gspread
    header = list(header)
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=title, rows=200, cols=len(header))
        print(f"Created tab '{title}'")

    existing = worksheet.get_all_values()
    if not any(cell.strip() for row in existing for cell in row):    # brand-new tab: [] or [[]]
        existing = []
    header_in_sheet = [LEGACY_LOG_COLUMN_NAMES.get(name, name) for name in existing[0][:len(header)]] if existing else []
    if existing and header_in_sheet != header:
        print(f"WARNING: tab '{title}' exists but doesn't look like this script's log "
              f"(columns differ) - not touching it. Rename/delete it or change log_worksheet in [sheet] of config.toml.")
        return None

    def restore_number(value):      # get_all_values() returns text; turn digit strings back into numbers
        return int(value) if isinstance(value, str) and re.fullmatch(r"\d+", value) else value

    rows_by_key: dict[tuple, list] = {}     # (date, student) -> row
    for old_row in existing[1:]:
        old_row = (old_row + [""] * len(header))[:len(header)]
        if old_row[0]:
            rows_by_key[(old_row[0], old_row[2])] = (
                [old_row[0], restore_number(old_row[1]), old_row[2]] + [restore_number(x) for x in old_row[3:]])
    added = kept = 0
    differences: list[tuple[list, list]] = []       # (row kept from the sheet, what the chat says now)
    for new_row in rows:
        key = (new_row[0], new_row[2])
        if key not in rows_by_key or overwrite:
            added += key not in rows_by_key
            rows_by_key[key] = new_row
        else:
            kept += 1
            if rows_by_key[key] != new_row:             # the chat now says something else: we keep the sheet's
                differences.append((rows_by_key[key], new_row))
    differing = len(differences)

    column_order = {name: i for i, name in enumerate(columns)}
    all_rows = sorted(rows_by_key.values(), key=lambda r: (r[0], column_order.get(r[2], 99), r[2]))

    if worksheet.row_count < len(all_rows) + 1:
        worksheet.resize(rows=len(all_rows) + 50)
    worksheet.clear()
    worksheet.update(values=[header] + all_rows, range_name="A1", value_input_option="RAW")
    print(f"Log updated: {added} new rows added, {kept} already there were left alone"
          + (f" ({differing} differ from the chat - the sheet's values are kept; --overwrite to replace them)"
             if differing else "")
          + ("." if not overwrite else " (--overwrite: rows replaced by the chat's version)."))
    if differences and not overwrite:
        def describe(row: list) -> str:
            return f"{row[-1]} min" + ("" if row[-2] == "" else f", {row[-2]} Anki cards")
        for old_row, new_row in differences[:15]:
            print(f"  - {old_row[0]} {old_row[2]}: the sheet has {describe(old_row)}; the chat says {describe(new_row)}")
        if differing > 15:
            print(f"  ... and {differing - 15} more")
    return worksheet, all_rows
