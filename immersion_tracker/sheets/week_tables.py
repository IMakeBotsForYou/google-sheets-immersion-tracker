"""The "week N" tables of the main tab: finding them, and filling in circles / crosses."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from ..errors import TrackerError
from ..planning import SheetCell
from ..settings import AppearanceSettings, SheetSettings
from ..textutil import normalize_name
from ..timeline import Calendar
from .client import OpenSheet
from .colors import hex_to_rgb


@dataclass
class WeekBlock:
    """One week table in the sheet."""
    header_row: int                     # 0-based row of the table header
    column_by_student: dict[str, int]   # normalised header text -> 0-based column
    column_names: list[str]             # header texts as written, left to right


@dataclass
class SheetSnapshot:
    """The week sheet as read at the start of the run."""
    spreadsheet: object
    worksheet: object
    values: list[list[str]]
    blocks: dict[int, WeekBlock]


def find_week_blocks(values: list[list[str]], tables: list[dict] | None, sheet: SheetSettings,
                     calendar: Calendar) -> dict[int, WeekBlock]:
    """{week number: block}.

    Preferred: the sheet's tables named "week N" (see week_table_name_regex).
    Fallback: scan for header_marker cells over the weekday labels, numbered 1, 2, 3... top to bottom.
    """
    def cell_text(row: int, col: int) -> str:
        return values[row][col].strip() if row < len(values) and col < len(values[row]) else ""

    expected_labels = calendar.expected_weekday_labels(sheet.weekday_labels)
    week_starts_on = calendar.settings.week_starts_on

    def read_block(header_row: int, first_col: int, end_col: int | None, description: str) -> WeekBlock | None:
        labels = [cell_text(header_row + 1 + i, first_col) for i in range(7)]
        if labels != expected_labels:
            print(f"  ({description}: weekday labels are {''.join(labels)!r} but week_starts_on="
                  f"{week_starts_on!r} expects {''.join(expected_labels)!r} - skipped)")
            return None
        total_cols = len(values[header_row]) if header_row < len(values) else 0
        column_by_student, column_names = {}, []
        for col in range(first_col + 1, end_col if end_col is not None else total_cols):
            header = cell_text(header_row, col)
            if header:
                column_by_student[normalize_name(header)] = col
                column_names.append(header)
        return WeekBlock(header_row, column_by_student, column_names)

    # --- preferred: tables named "week N"
    blocks: dict[int, WeekBlock] = {}
    name_regex = re.compile(sheet.week_table_name_regex, re.I)
    for table in tables or []:
        name_match = name_regex.match(table.get("name", ""))
        if not name_match:
            continue
        week_number = int(name_match.group(1))
        table_range = table.get("range", {})
        top = table_range.get("startRowIndex", 0)
        left = table_range.get("startColumnIndex", 0)
        right = table_range.get("endColumnIndex")
        header_row = next((r for r in (top, top + 1) if cell_text(r, left) == sheet.header_marker), None)
        if header_row is None:
            print(f"  (table '{table['name']}': no '{sheet.header_marker}' header at its top-left corner - skipped)")
            continue
        if week_number in blocks:
            print(f"  (two tables are named 'week {week_number}' - using the first one)")
            continue
        block = read_block(header_row, left, right, f"table '{table['name']}'")
        if block:
            blocks[week_number] = block
    if blocks:
        return blocks

    # --- fallback: scan the cells for the header marker
    if tables:
        print(f"  (no usable tables matching {sheet.week_table_name_regex!r}; "
              f"scanning for '{sheet.header_marker}' headers instead)")
    for row in range(len(values)):
        for col in range(len(values[row])):
            if cell_text(row, col) == sheet.header_marker:
                block = read_block(row, col, None, f"table at row {row + 1}")
                if block:
                    blocks[len(blocks) + 1] = block
    return blocks


def load_week_blocks(spreadsheet, worksheet, values: list[list[str]] | None, sheet: SheetSettings,
                     calendar: Calendar) -> dict[int, WeekBlock]:
    tables: list[dict] = []
    try:
        metadata = spreadsheet.fetch_sheet_metadata(
            params={"fields": "sheets(properties(sheetId),tables(tableId,name,range))"})
        for entry in metadata.get("sheets", []):
            if entry["properties"]["sheetId"] == worksheet.id:
                tables = entry.get("tables", [])
    except Exception as error:
        print(f"  (couldn't read table names from the sheet: {error})")
    return find_week_blocks(values if values is not None else worksheet.get_all_values(), tables, sheet, calendar)


def read_snapshot(open_sheet: OpenSheet, sheet: SheetSettings, calendar: Calendar, required: bool,
                  fallback_note: str = "") -> SheetSnapshot | None:
    """Open the sheet and read the week tables.  required=False (dry run): on any problem return None."""
    try:
        spreadsheet, worksheet = open_sheet()
        values = worksheet.get_all_values()
        return SheetSnapshot(spreadsheet, worksheet, values, load_week_blocks(spreadsheet, worksheet, values, sheet, calendar))
    except Exception as error:      # missing key file, no access, gspread not installed...
        if required:
            if isinstance(error, TrackerError):     # already says what to do (missing id / key...)
                raise
            raise TrackerError(f"Couldn't open the Google Sheet: {type(error).__name__}: {error}") from error
        print(f"(couldn't read the sheet - {type(error).__name__}: {error}\n {fallback_note})")
        return None


def sheet_order(blocks: dict[int, WeekBlock]) -> list[str]:
    """The left-to-right order of the student headers (normalised) in the week tables:
    the first table wins, headers that only appear in later tables go after."""
    order: dict[str, None] = {}
    for week in sorted(blocks):
        for header in blocks[week].column_names:
            order.setdefault(normalize_name(header), None)
    return list(order)


def cell_update_request(sheet_id: int, row: int, col: int, cell: SheetCell, appearance: AppearanceSettings) -> dict:
    """Sheets API request: set one cell's text and background colour."""
    color = hex_to_rgb(appearance.green if cell.green else appearance.red)
    return {"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": row, "endRowIndex": row + 1,
                  "startColumnIndex": col, "endColumnIndex": col + 1},
        "cell": {"userEnteredValue": {"stringValue": cell.text},
                 "userEnteredFormat": {"backgroundColor": color}},
        "fields": "userEnteredValue,userEnteredFormat.backgroundColor",
    }}


def is_filled(text: str, marks: str) -> bool:
    """Does this cell already hold circles / a cross?"""
    return any(char in marks for char in text)


def write_week_tables(plan: dict[tuple[str, date], SheetCell], day1: date, overwrite: bool, snapshot: SheetSnapshot,
                      sheet: SheetSettings, appearance: AppearanceSettings, calendar: Calendar):
    """Write the plan into the week tables.  Returns the spreadsheet."""
    spreadsheet, worksheet, values, blocks = snapshot.spreadsheet, snapshot.worksheet, snapshot.values, snapshot.blocks
    if not blocks:
        raise TrackerError(
            f"No week tables found in '{sheet.worksheet}' (looking for tables named like 'week 1', "
            f"or a '{sheet.header_marker}' header over "
            f"{''.join(calendar.expected_weekday_labels(sheet.weekday_labels))}). "
            f"Check week_table_name_regex / weekday_labels in [sheet] and week_starts_on in [calendar] of config.toml.")
    print(f"Found {len(blocks)} week tables (week {min(blocks)} - week {max(blocks)})")

    week1_start = calendar.week1_first_row_date(day1)
    requests = []
    skipped_filled = 0
    missing_weeks: set[int] = set()
    missing_columns: set[str] = set()
    for (column_name, day), cell in plan.items():
        week_index, row_in_week = divmod((day - week1_start).days, 7)
        block = blocks.get(week_index + 1)
        if block is None:
            missing_weeks.add(week_index + 1)
            continue
        col = block.column_by_student.get(normalize_name(column_name))
        if col is None:
            missing_columns.add(column_name)
            continue
        sheet_row = block.header_row + 1 + row_in_week
        current = values[sheet_row][col] if sheet_row < len(values) and col < len(values[sheet_row]) else ""
        if not overwrite and is_filled(current, appearance.filled_cell_marks):
            skipped_filled += 1
            continue
        requests.append(cell_update_request(worksheet.id, sheet_row, col, cell, appearance))

    if requests:
        spreadsheet.batch_update({"requests": requests})
    print(f"Updated {len(requests)} cells.")
    if skipped_filled:
        print(f"Left {skipped_filled} cells alone that already had ◯ / ✖ in them (--overwrite to replace them).")
    if missing_weeks:
        print(f"WARNING: no table named 'week N' for N in {sorted(missing_weeks)} - those days were not written.")
    if missing_columns:
        print(f"WARNING: no column header matching {sorted(missing_columns)} - re-run --setup --all to fix.")
    return spreadsheet
