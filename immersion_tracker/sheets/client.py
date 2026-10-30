"""Connecting to the spreadsheet."""
from __future__ import annotations

from typing import Callable

from ..credentials import GoogleCredentials
from ..settings import SheetSettings

OpenSheet = Callable[[], tuple]         # () -> (spreadsheet, week worksheet)


def make_sheet_opener(credentials_loader: Callable[[], GoogleCredentials], sheet: SheetSettings) -> OpenSheet:
    """A function that connects (lazily - credentials are only needed when the sheet is really used)
    and returns (spreadsheet, the worksheet holding the week tables)."""
    def open_sheet():
        spreadsheet = credentials_loader().open_spreadsheet()
        return spreadsheet, spreadsheet.worksheet(sheet.worksheet)
    return open_sheet
