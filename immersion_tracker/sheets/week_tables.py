"""The "week N" tables of the main tab: finding them, and filling in circles / crosses."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Sequence

from ..errors import TrackerError
from ..planning import SheetCell
from ..settings import AppearanceSettings, ConjugationSettings, SheetSettings
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
                     calendar: Calendar, name_regex: str | None = None, first_number: int = 1) -> dict[int, WeekBlock]:
    """{week number: block}.

    Preferred: the sheet's tables whose name matches `name_regex` (default: week_table_name_regex, "week N").
    Fallback: scan for header_marker cells over the weekday labels, numbered first_number, +1, +2... top to bottom.
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
    name_pattern = re.compile(name_regex or sheet.week_table_name_regex, re.I)
    for table in tables or []:
        name_match = name_pattern.match(table.get("name", ""))
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
        print(f"  (no usable tables matching {name_regex or sheet.week_table_name_regex!r}; "
              f"scanning for '{sheet.header_marker}' headers instead)")
    for row in range(len(values)):
        for col in range(len(values[row])):
            if cell_text(row, col) == sheet.header_marker:
                block = read_block(row, col, None, f"table at row {row + 1}")
                if block:
                    blocks[first_number + len(blocks)] = block
    return blocks


def load_week_blocks(spreadsheet, worksheet, values: list[list[str]] | None, sheet: SheetSettings,
                     calendar: Calendar, name_regex: str | None = None, first_number: int = 1) -> dict[int, WeekBlock]:
    tables: list[dict] = []
    try:
        metadata = spreadsheet.fetch_sheet_metadata(
            params={"fields": "sheets(properties(sheetId),tables(tableId,name,range))"})
        for entry in metadata.get("sheets", []):
            if entry["properties"]["sheetId"] == worksheet.id:
                tables = entry.get("tables", [])
    except Exception as error:
        print(f"  (couldn't read table names from the sheet: {error})")
    return find_week_blocks(values if values is not None else worksheet.get_all_values(), tables, sheet, calendar,
                            name_regex, first_number)


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


def read_conjugation_snapshot(spreadsheet, conjugations: ConjugationSettings, sheet: SheetSettings,
                              calendar: Calendar) -> SheetSnapshot | None:
    """The conjugations tab, read like the main one.  None (with a note) if the sheet has no such tab."""
    import gspread
    try:
        worksheet = spreadsheet.worksheet(conjugations.worksheet)
    except gspread.WorksheetNotFound:
        print(f"(no '{conjugations.worksheet}' tab in the sheet - conjugations not written)")
        return None
    values = worksheet.get_all_values()
    blocks = load_week_blocks(spreadsheet, worksheet, values, sheet, calendar,
                              conjugations.table_name_regex, conjugations.first_week)
    return SheetSnapshot(spreadsheet, worksheet, values, blocks)


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


def _mark_sets(appearance: AppearanceSettings) -> tuple[set[str], set[str]]:
    """(characters that count as a circle, characters that count as a cross)."""
    crosses = set(appearance.cross_marks) | set(appearance.cross)
    circles = (set(appearance.filled_cell_marks) | set(appearance.circle)) - crosses
    return circles, crosses


def cell_state(text: str, appearance: AppearanceSettings) -> str:
    """What a cell currently holds: "circles", "cross" or "empty" (anything else is treated as empty)."""
    circles, crosses = _mark_sets(appearance)
    if any(char in circles for char in text):
        return "circles"
    if any(char in crosses for char in text):
        return "cross"
    return "empty"


def circle_total(text: str, appearance: AppearanceSettings) -> int:
    circles, _ = _mark_sets(appearance)
    return sum(char in circles for char in text)


@dataclass
class CellWrites:
    """What writing the plan into the sheet would do."""
    requests: list[dict] = field(default_factory=list)
    skipped: int = 0                                                    # cells left alone
    late_fills: list[tuple[str, date, str, str]] = field(default_factory=list)   # (student, day, was, now): a ✖ replaced by circles
    conflicts: list[tuple[str, date, str, str]] = field(default_factory=list)    # (student, day, sheet has, chat says): circles kept
    missing_weeks: set[int] = field(default_factory=set)
    missing_columns: set[str] = field(default_factory=set)


def decide_cell_writes(plan: dict[tuple[str, date], SheetCell], day1: date, overwrite: bool, snapshot: SheetSnapshot,
                       appearance: AppearanceSettings, calendar: Calendar) -> CellWrites:
    """Compare the plan with the sheet, cell by cell:

    - an empty cell is written;
    - a cell that already shows circles is left alone (and, if the chat says a different number of circles,
      that is reported as a conflict);
    - a cell that shows a ✖ is replaced when the plan has circles for it - a LATE report for a day that had
      already been crossed out - and left as it is when there is still nothing to put there;
    - with `overwrite` every cell is written.
    """
    worksheet, values, blocks = snapshot.worksheet, snapshot.values, snapshot.blocks
    writes = CellWrites()
    week1_start = calendar.week1_first_row_date(day1)
    for (column_name, day), cell in plan.items():
        week_index, row_in_week = divmod((day - week1_start).days, 7)
        block = blocks.get(week_index + 1)
        if block is None:
            writes.missing_weeks.add(week_index + 1)
            continue
        col = block.column_by_student.get(normalize_name(column_name))
        if col is None:
            writes.missing_columns.add(column_name)
            continue
        sheet_row = block.header_row + 1 + row_in_week
        current = values[sheet_row][col] if sheet_row < len(values) and col < len(values[sheet_row]) else ""
        if not overwrite:
            state = cell_state(current, appearance)
            if state == "circles":
                writes.skipped += 1
                if cell.green and circle_total(current, appearance) != circle_total(cell.text, appearance):
                    writes.conflicts.append((column_name, day, current.strip(), cell.text))
                continue
            if state == "cross":
                if not cell.green:              # still nothing to report: the ✖ stays
                    writes.skipped += 1
                    continue
                writes.late_fills.append((column_name, day, current.strip(), cell.text))
        writes.requests.append(cell_update_request(worksheet.id, sheet_row, col, cell, appearance))
    return writes


MAX_LISTED = 15


def _print_outcome(writes: CellWrites, tag: str, would: bool) -> None:
    print(f"{tag}{'Would update' if would else 'Updated'} {len(writes.requests)} cells.")
    if writes.late_fills:
        print(f"{tag}{'Would fill' if would else 'Filled'} in {len(writes.late_fills)} late report(s) over a cross:")
        for student, day, was, now in writes.late_fills[:MAX_LISTED]:
            print(f"{tag}  - {student} {day.isoformat()}: {was} -> {now}")
        if len(writes.late_fills) > MAX_LISTED:
            print(f"{tag}  ... and {len(writes.late_fills) - MAX_LISTED} more")
    if writes.skipped:
        print(f"{tag}Left {writes.skipped} cells alone that already had ◯ / ✖ in them (--overwrite to replace them).")
    for student, day, shown, chat in writes.conflicts[:MAX_LISTED]:
        print(f"{tag}WARNING: {student} {day.isoformat()}: the sheet already shows {shown} but the chat says {chat} "
              f"- left alone (--overwrite to replace it)")
    if len(writes.conflicts) > MAX_LISTED:
        print(f"{tag}WARNING: ... and {len(writes.conflicts) - MAX_LISTED} more cells where the sheet differs from the chat")
    if writes.missing_weeks:
        print(f"{tag}WARNING: no table for week {sorted(writes.missing_weeks)} - those days were not written.")
    if writes.missing_columns:
        print(f"{tag}WARNING: no column header matching {sorted(writes.missing_columns)} - re-run --setup --all to fix.")


def _check_blocks(snapshot: SheetSnapshot, sheet: SheetSettings, calendar: Calendar, tag: str,
                  tab_title: str | None, table_example: str) -> None:
    if not snapshot.blocks:
        raise TrackerError(
            f"{tag}No week tables found in '{tab_title or sheet.worksheet}' (looking for tables named like "
            f"'{table_example}', or a '{sheet.header_marker}' header over "
            f"{''.join(calendar.expected_weekday_labels(sheet.weekday_labels))}). "
            f"Check the table names / weekday_labels in config.toml (and week_starts_on in [calendar]).")
    print(f"{tag}Found {len(snapshot.blocks)} week tables (week {min(snapshot.blocks)} - week {max(snapshot.blocks)})")


def write_week_tables(plan: dict[tuple[str, date], SheetCell], day1: date, overwrite: bool, snapshot: SheetSnapshot,
                      sheet: SheetSettings, appearance: AppearanceSettings, calendar: Calendar,
                      tab_title: str | None = None, table_example: str = "week 1"):
    """Write the plan into the week tables.  Returns the spreadsheet.
    `tab_title` is only for the extra tabs (conjugations): their messages are tagged with it."""
    tag = f"[{tab_title}] " if tab_title else ""
    _check_blocks(snapshot, sheet, calendar, tag, tab_title, table_example)
    writes = decide_cell_writes(plan, day1, overwrite, snapshot, appearance, calendar)
    if writes.requests:
        snapshot.spreadsheet.batch_update({"requests": writes.requests})
    _print_outcome(writes, tag, would=False)
    return snapshot.spreadsheet


def preview_week_tables(plan: dict[tuple[str, date], SheetCell], day1: date, overwrite: bool, snapshot: SheetSnapshot,
                        sheet: SheetSettings, appearance: AppearanceSettings, calendar: Calendar,
                        tab_title: str | None = None, table_example: str = "week 1") -> None:
    """What write_week_tables would do to the sheet as it is now - without writing anything (for --dry-run)."""
    tag = f"[{tab_title}] " if tab_title else ""
    _check_blocks(snapshot, sheet, calendar, tag, tab_title, table_example)
    _print_outcome(decide_cell_writes(plan, day1, overwrite, snapshot, appearance, calendar), tag, would=True)
