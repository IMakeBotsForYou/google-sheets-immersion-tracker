"""Two line charts on the log tab: hours of immersion (top) and new Anki cards (bottom), one line per student.

The numbers live in a small helper tab that is rewritten on every run (a Sheets chart can't pivot the long
log format by itself); the charts are replaced on every run too, so they always match the log.
Both charts get the same anchor column, offset and width, so they line up one above the other.
"""
from __future__ import annotations

import math
from itertools import accumulate
from typing import Sequence

from ..console import print_table
from ..settings import ChartSettings
from .colors import hex_to_rgb
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
        minutes[column] = [_number(cell[-1]) if cell else 0 for cell in cells]
        cards[column] = [_number(cell[-2]) if cell else 0 for cell in cells]

    def finish(series: dict[str, list[float]], cumulative: bool, scale: float) -> dict[str, list]:
        result = {}
        for column, values in series.items():
            values = list(accumulate(values)) if cumulative else values
            result[column] = [round(value / scale, 2) if scale != 1 else int(value) for value in values]
        return result

    return (days, finish(minutes, settings.hours_cumulative, 60), finish(cards, settings.cards_cumulative, 1))


def chart_grid(days: list[int], columns: Sequence[str], hours: dict, cards: dict) -> list[list]:
    """The helper tab: hours block, one empty column, cards block - both with the day number in front."""
    columns = list(columns)
    header = [DAY_HEADER] + columns + [""] + [DAY_HEADER] + columns
    body = [[day] + [hours[column][i] for column in columns] + [""] + [day] + [cards[column][i] for column in columns]
            for i, day in enumerate(days)]
    return [header] + body


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
                 settings: ChartSettings, log_column_count: int) -> None:
    """Rewrite the helper data tab and (re)draw the two charts on the log tab."""
    import gspread
    columns = list(columns)
    tables = build_chart_tables(log_rows, columns, today_number, settings)
    if tables is None:
        print("No logged days yet - no charts drawn.")
        return
    days, hours, cards = tables

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
    grid = chart_grid(days, columns, hours, cards)
    width = len(grid[0])
    if data_sheet.row_count < len(grid) + 20 or data_sheet.col_count < width:
        data_sheet.resize(rows=max(data_sheet.row_count, len(grid) + 20), cols=max(data_sheet.col_count, width))
    data_sheet.clear()
    data_sheet.update(values=grid, range_name="A1", value_input_option="RAW")

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
