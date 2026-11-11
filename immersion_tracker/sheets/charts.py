"""Two line charts on the log tab: hours of immersion (top) and new Anki cards (bottom), one line per student.

The numbers live in a small helper tab that is rewritten on every run (a Sheets chart can't pivot the long
log format by itself); the charts are replaced on every run too, so they always match the log.
Both charts get the same anchor column, offset and width, so they line up one above the other.

The helper tab is add-only, like the circles in the week tables: a cell that already holds a number is
never replaced, only empty cells are filled (new days, new students).  ``overwrite`` rebuilds it from the log.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import accumulate
from typing import Sequence

from ..console import print_table
from ..settings import ChartSettings
from ..textutil import normalize_name
from .colors import hex_to_rgb
from .log import ANKI_COLUMN, TOTAL_COLUMN
from .palette import student_colors

DAY_HEADER = "יום"          # A1 of the helper tab - also how the script recognises its own tab
X_AXIS_TITLE = "ימים מתחילת האתגר"
HOURS_Y_TITLE = "שעות חשיפה"
CARDS_Y_TITLE = "קלפי אנקי חדשים"
DEFAULT_ROW_HEIGHT_PX = 21
DEFAULT_COLUMN_WIDTH_PX = 100


def chart_column(settings: ChartSettings, log_column_count: int) -> int:
    """Column (0 = A) the charts are anchored at: right after the log table, leaving one empty column."""
    return log_column_count + 1 if settings.column is None else settings.column


def chart_titles(settings: ChartSettings) -> dict[str, str]:
    hours = "מצטבר" if settings.hours_cumulative else "ביום"
    cards = "מצטבר" if settings.cards_cumulative else "ביום"
    return {"hours": f"שעות חשיפה – {hours}", "cards": f"קלפי אנקי חדשים – {cards}"}


def all_possible_chart_titles() -> set[str]:
    """Titles the charts can have with either setting - used to find (and replace) the script's old charts."""
    return ({f"שעות חשיפה – {word}" for word in ("מצטבר", "ביום")}
            | {f"קלפי אנקי חדשים – {word}" for word in ("מצטבר", "ביום")})


def print_chart_colors(columns: Sequence[str]) -> None:
    colors = student_colors(list(columns))
    print("\nChart colours:")
    print_table(["תלמיד", "צבע"], [[column, colors[column]] for column in columns])


def _number(value) -> float:
    return value if isinstance(value, (int, float)) else 0


def build_chart_tables(log_rows: list[list], columns: Sequence[str], today_number: int, settings: ChartSettings):
    """-> (day numbers, {student: hours}, {student: new cards}) or None if there's nothing yet.
    Days run from the first logged day to the last logged day (or yesterday, if later) - a finished day with
    no report counts as 0.  Running totals are applied according to the chart settings."""
    rows = [row for row in log_rows if isinstance(row[1], int) and row[1] <= today_number]
    if not rows:
        return None
    first = min(row[1] for row in rows)
    last = max([row[1] for row in rows] + [today_number - 1])
    by_cell = {(row[2], row[1]): row for row in rows}
    days = list(range(first, last + 1))
    minutes: dict[str, list[float]] = {}
    cards: dict[str, list[float]] = {}
    for column in columns:
        cells = [by_cell.get((column, day)) for day in days]
        minutes[column] = [_number(cell[TOTAL_COLUMN]) if cell else 0 for cell in cells]
        cards[column] = [_number(cell[ANKI_COLUMN]) if cell else 0 for cell in cells]

    def finish(series: dict[str, list[float]], cumulative: bool, scale: float) -> dict[str, list]:
        result = {}
        for column, values in series.items():
            values = list(accumulate(values)) if cumulative else values
            result[column] = [round(value / scale, 2) if scale != 1 else int(value) for value in values]
        return result

    return (days, finish(minutes, settings.hours_cumulative, 60), finish(cards, settings.cards_cumulative, 1))


def chart_grid(days: list[int], columns: Sequence[str], hours: dict, cards: dict, marker: str = "") -> list[list]:
    """The helper tab: hours block, a separator column, cards block - both with the day number in front.
    A None value is left blank.  The separator's header holds `marker` (see mode_marker)."""
    columns = list(columns)
    blank = lambda value: "" if value is None else value
    header = [DAY_HEADER] + columns + [marker] + [DAY_HEADER] + columns
    body = [[day] + [blank(hours[column][i]) for column in columns] + [""]
            + [day] + [blank(cards[column][i]) for column in columns]
            for i, day in enumerate(days)]
    return [header] + body


# ----------------------------------------------------------------------------
# Add-only merging with what is already in the helper tab
# ----------------------------------------------------------------------------
_MODE_RE = re.compile(r"hours=(\S+)\s+cards=(\S+)")


def _mode_word(cumulative: bool) -> str:
    return "cumulative" if cumulative else "per-day"


def mode_marker(settings: ChartSettings) -> str:
    """Written in the separator column's header, so a later run can tell if running totals were switched on/off
    (old numbers of the other kind must not be mixed with new ones)."""
    return f"hours={_mode_word(settings.hours_cumulative)} cards={_mode_word(settings.cards_cumulative)}"


def _parse_number(text: str):
    """Cell text -> int / float (the sheet may show a decimal comma).  Anything else is kept as text."""
    text = text.strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    if re.fullmatch(r"-?\d+,\d{1,2}", text):              # decimal comma: 2,08
        return float(text.replace(",", "."))
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", text):       # thousands separator: 1,234
        return int(text.replace(",", ""))
    return text


def _agrees(kept_value, from_log) -> bool:
    """Is a number already in the tab the one the log gives (up to the 2-decimal rounding)?"""
    return from_log is not None and abs(kept_value - from_log) <= 0.011


@dataclass
class StoredChartData:
    """What the helper tab already holds."""
    students: list[str]                 # headers as written (hours block first, then any only in the cards block)
    hours: dict[tuple[int, str], object]    # (day, normalised student) -> value, filled cells only
    cards: dict[tuple[int, str], object]
    hours_mode: str | None              # None = tab written before the marker existed
    cards_mode: str | None


def read_stored_data(grid: list[list[str]]) -> StoredChartData | None:
    """Parse the helper tab as written by chart_grid.  None if it is empty or not laid out like ours."""
    if not grid or not grid[0] or grid[0][0].strip() != DAY_HEADER:
        return None
    header = [cell.strip() for cell in grid[0]]
    try:
        second = header.index(DAY_HEADER, 1)            # where the cards block starts
    except ValueError:
        return None
    first_students = header[1:second - 1]               # header[second - 1] is the separator
    second_students = [name for name in header[second + 1:] if name]
    marker = _MODE_RE.fullmatch(header[second - 1]) if second >= 1 else None

    def read_block(day_column: int, students: list[str], first_column: int) -> dict:
        values = {}
        for row in grid[1:]:
            day_text = row[day_column].strip() if day_column < len(row) else ""
            if not day_text.isdigit():
                continue
            for offset, name in enumerate(students):
                column = first_column + offset
                text = row[column].strip() if column < len(row) else ""
                if text != "":
                    values[(int(day_text), normalize_name(name))] = _parse_number(text)
        return values

    known = {normalize_name(name) for name in first_students}
    return StoredChartData(
        students=first_students + [name for name in second_students if normalize_name(name) not in known],
        hours=read_block(0, first_students, 1),
        cards=read_block(second, second_students, second + 1),
        hours_mode=marker.group(1) if marker else None,
        cards_mode=marker.group(2) if marker else None)


@dataclass
class MergedChartData:
    days: list[int]
    columns: list[str]
    hours: dict[str, list]              # student -> one value per day (None = blank)
    cards: dict[str, list]
    kept: int                           # cells that were already filled and were left alone
    added: int                          # cells filled in now
    notes: list[str]


def merge_chart_data(days: list[int], hours: dict, cards: dict, columns: Sequence[str],
                     stored: StoredChartData | None, settings: ChartSettings, overwrite: bool) -> MergedChartData:
    """Computed numbers + what the tab already holds.  A filled cell is never replaced (unless `overwrite`);
    days and students already in the tab stay even if they are no longer in the log / the people file."""
    columns = list(columns)
    notes: list[str] = []
    hours_keep: dict = {}
    cards_keep: dict = {}
    extra: list[str] = []
    if stored and overwrite:
        notes.append("rebuilt from the log (--overwrite)")
    elif stored:
        wanted = {"hours": _mode_word(settings.hours_cumulative), "cards": _mode_word(settings.cards_cumulative)}
        for name, keep, found in (("hours", stored.hours, stored.hours_mode), ("cards", stored.cards, stored.cards_mode)):
            if found in (None, wanted[name]):       # None: an older tab without the marker - assume it matches
                (hours_keep if name == "hours" else cards_keep).update(keep)
            else:
                notes.append(f"{name} are now {wanted[name]} (the tab had {found}): that block was rebuilt from the log")
        current = {normalize_name(column) for column in columns}
        extra = [name for name in stored.students if normalize_name(name) not in current]

    all_columns = columns + extra
    all_days = sorted(set(days) | {day for day, _ in list(hours_keep) + list(cards_keep)})
    position = {day: i for i, day in enumerate(days)}

    def build(computed: dict, keep: dict, cumulative: bool):
        merged, kept, added = {}, 0, 0
        for column in all_columns:
            key, values = normalize_name(column), []
            previous = None                 # the last number in this column (kept or new)
            previous_from_log = None        # what the log itself says for the previous day
            for day in all_days:
                from_log = computed[column][position[day]] if column in computed and day in position else None
                if (day, key) in keep:
                    value = keep[(day, key)]
                    kept += 1
                elif from_log is None:
                    value = None
                else:
                    value = from_log
                    if cumulative and isinstance(previous, (int, float)) and not _agrees(previous, previous_from_log):
                        # The numbers before this day were changed by hand (or came from an older log), so a running
                        # total taken from the log would jump.  Continue from what the tab holds instead.
                        value = round(previous + from_log - (previous_from_log or 0), 2)
                    added += 1
                values.append(value)
                if isinstance(value, (int, float)):
                    previous = value
                previous_from_log = from_log
            merged[column] = values
        return merged, kept, added

    merged_hours, kept_hours, added_hours = build(hours, hours_keep, settings.hours_cumulative)
    merged_cards, kept_cards, added_cards = build(cards, cards_keep, settings.cards_cumulative)
    return MergedChartData(all_days, all_columns, merged_hours, merged_cards,
                           kept_hours + kept_cards, added_hours + added_cards, notes)


def line_chart_request(*, title: str, y_title: str, data_sheet_id: int, first_col: int, row_count: int,
                       columns: Sequence[str], colors: dict[str, str], anchor_sheet_id: int, anchor_row: int,
                       anchor_column: int, settings: ChartSettings) -> dict:
    """addChart request: one line per student, X = the day column at first_col, students in the columns after it."""
    def source(col: int) -> dict:
        return {"sourceRange": {"sources": [{"sheetId": data_sheet_id, "startRowIndex": 0, "endRowIndex": row_count,
                                             "startColumnIndex": col, "endColumnIndex": col + 1}]}}
    series = [{"series": source(first_col + 1 + i),
               "targetAxis": "LEFT_AXIS",
               "colorStyle": {"rgbColor": hex_to_rgb(colors[column])},
               "lineStyle": {"type": "SOLID", "width": settings.line_width},
               "pointStyle": {"shape": "CIRCLE", "size": 6}}
              for i, column in enumerate(columns)]
    return {"addChart": {"chart": {
        "spec": {
            "title": title,
            "titleTextPosition": {"horizontalAlignment": "CENTER"},
            "basicChart": {
                "chartType": "LINE",
                "legendPosition": "RIGHT_LEGEND",
                "headerCount": 1,
                "axis": [{"position": "BOTTOM_AXIS", "title": X_AXIS_TITLE},
                         {"position": "LEFT_AXIS", "title": y_title,
                          "viewWindowOptions": {"viewWindowMode": "EXPLICIT", "viewWindowMin": 0}}],     # EXPLICIT, or the min is ignored
                "domains": [{"domain": source(first_col)}],
                "series": series,
            },
        },
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": anchor_sheet_id, "rowIndex": anchor_row, "columnIndex": anchor_column},
            "offsetXPixels": 0, "offsetYPixels": 0,
            "widthPixels": settings.width_px, "heightPixels": settings.height_px}},
    }}}


def write_charts(spreadsheet, log_worksheet, log_rows: list[list], today_number: int, columns: Sequence[str],
                 settings: ChartSettings, log_column_count: int, overwrite: bool = False) -> None:
    """Add to the helper data tab (filled cells are kept) and (re)draw the two charts on the log tab."""
    import gspread
    columns = list(columns)
    tables = build_chart_tables(log_rows, columns, today_number, settings)
    if tables is None:
        print("No logged days yet - no charts drawn.")
        return
    computed_days, computed_hours, computed_cards = tables

    # --- helper tab with the numbers
    try:
        data_sheet = spreadsheet.worksheet(settings.data_worksheet)
    except gspread.WorksheetNotFound:
        data_sheet = spreadsheet.add_worksheet(title=settings.data_worksheet, rows=200, cols=2 * len(columns) + 3)
        print(f"Created tab '{settings.data_worksheet}' (the charts read their numbers from it)")
    existing = data_sheet.get_all_values()
    first_cell = existing[0][0].strip() if existing and existing[0] else ""
    if first_cell and first_cell != DAY_HEADER:
        print(f"WARNING: tab '{settings.data_worksheet}' exists but doesn't look like this script's chart data "
              f"- charts not drawn. Rename/delete it or change data_worksheet in [charts] of config.toml.")
        return
    merged = merge_chart_data(computed_days, computed_hours, computed_cards, columns,
                              read_stored_data(existing), settings, overwrite)
    days, columns = merged.days, merged.columns         # the tab may hold days / students the log no longer has
    grid = chart_grid(days, columns, merged.hours, merged.cards, mode_marker(settings))
    width = len(grid[0])
    if data_sheet.row_count < len(grid) + 20 or data_sheet.col_count < width:
        data_sheet.resize(rows=max(data_sheet.row_count, len(grid) + 20), cols=max(data_sheet.col_count, width))
    data_sheet.clear()
    data_sheet.update(values=grid, range_name="A1", value_input_option="RAW")
    print(f"Chart data: kept {merged.kept} filled cells, added {merged.added} new ones"
          + "".join(f"\n  ({note})" for note in merged.notes))

    # --- make sure the log tab has room (an anchor cell outside the grid is refused)
    anchor_column = chart_column(settings, log_column_count)
    second_row = math.ceil((settings.height_px + settings.gap_px) / DEFAULT_ROW_HEIGHT_PX)
    need_rows = second_row + math.ceil(settings.height_px / DEFAULT_ROW_HEIGHT_PX) + 2
    need_cols = anchor_column + math.ceil(settings.width_px / DEFAULT_COLUMN_WIDTH_PX) + 1
    if log_worksheet.row_count < need_rows or log_worksheet.col_count < need_cols:
        log_worksheet.resize(rows=max(log_worksheet.row_count, need_rows), cols=max(log_worksheet.col_count, need_cols))

    # --- replace the script's old charts on the log tab by new ones
    requests = []
    metadata = spreadsheet.fetch_sheet_metadata(
        params={"fields": "sheets(properties(sheetId),charts(chartId,spec(title)))"})
    old_titles = all_possible_chart_titles()
    for sheet in metadata.get("sheets", []):
        if sheet["properties"]["sheetId"] != log_worksheet.id:
            continue
        for chart in sheet.get("charts", []):
            if chart.get("spec", {}).get("title") in old_titles:
                requests.append({"deleteEmbeddedObject": {"objectId": chart["chartId"]}})

    colors = student_colors(columns)
    titles = chart_titles(settings)
    common = dict(data_sheet_id=data_sheet.id, row_count=len(grid), columns=columns, colors=colors,
                  anchor_sheet_id=log_worksheet.id, anchor_column=anchor_column, settings=settings)
    requests.append(line_chart_request(title=titles["hours"], y_title=HOURS_Y_TITLE, first_col=0, anchor_row=0, **common))
    requests.append(line_chart_request(title=titles["cards"], y_title=CARDS_Y_TITLE, first_col=len(columns) + 2,
                                       anchor_row=second_row, **common))
    spreadsheet.batch_update({"requests": requests})
    print(f"Charts updated on '{log_worksheet.title}' (day {days[0]} - day {days[-1]}, {len(columns)} students).")
