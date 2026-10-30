"""All tunable behaviour, as typed settings.

Every value has a built-in default; ``config.toml`` (see ``config.example.toml``) overrides them.
Unknown keys are rejected so a typo in the file can't silently do nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import ConfigError
from .textutil import normalize_name

try:
    import tomllib                      # Python 3.11+
except ModuleNotFoundError:             # pragma: no cover - older Pythons
    import tomli as tomllib

# Activity name (as shown in the log) -> words that can start its line in a report.
DEFAULT_ACTIVITIES: dict[str, tuple[str, ...]] = {
    "צפייה": ("צפייה", "צפיה", "יוטיוב", "יוטוב"),     # "יוטיוב" lines count as צפייה (added up if both appear)
    "קריאה": ("קריאה",),
    "שמיעה": ("שמיעה", "שמיעה פסיבית", "הקשבה"),         # a "שמיעה פסיבית" line is added to שמיעה
    "רילז": ("רילז", "ריילז"),
}
DEFAULT_ANKI_WORDS: tuple[str, ...] = ("אנקי", "anki")


@dataclass(frozen=True)
class CalendarSettings:
    week_starts_on: str = "sunday"          # weekday of the first row of every week table
    day_1_weekday: str = "thursday"         # weekday Day #1 falls on
    day_1_date: date | None = None          # None = work it out from the chat
    skip_until_week: int = 1                # leave everything before the first row of this week table untouched
    skip_first_days: int | None = None      # manual alternative: leave exactly the first N days untouched
    timezone: str = "Asia/Jerusalem"        # the days are counted in this time zone
    chat_timezone: str | None = None        # time zone of the phone that exported the chat (None = same as `timezone`)
    day_ends_at: dtime = dtime(5, 0)        # a day runs until this time the next morning
    format_start: datetime | None = None    # messages before this (chat time) are old-format and not read


@dataclass(frozen=True)
class ReportSettings:
    activities: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_ACTIVITIES))
    anki_words: tuple[str, ...] = DEFAULT_ANKI_WORDS
    rounding: str = "floor"                 # minutes -> circles: "floor" (1h35 = 1), "round" (= 2), "ceil"
    multiple_reports: str = "last"          # several reports for one day: "last", "sum", "max"


@dataclass(frozen=True)
class SheetSettings:
    worksheet: str = "חשיפה"                 # the tab with the week tables
    log_worksheet: str | None = "יומן חשיפה"  # per-day breakdown tab; None / "" = don't write it
    week_table_name_regex: str = r"^\s*week\s*(\d+)\s*$"
    header_marker: str = "曜日"               # header text of the weekday column
    weekday_labels: tuple[str, ...] = ("月", "火", "水", "木", "金", "土", "日")     # row labels, MONDAY first


@dataclass(frozen=True)
class AppearanceSettings:
    circle: str = "◯"
    cross: str = "✖"
    green: str = "#34A853"
    red: str = "#EA4335"
    overwrite_filled_cells: bool = False    # False = cells already holding ◯ / ✖ are left alone
    filled_cell_marks: str = "◯○⭕●⚪✖✗✘✕×❌xX"


@dataclass(frozen=True)
class ChartSettings:
    enabled: bool = True
    data_worksheet: str = "נתוני גרפים"      # helper tab the charts read from (rewritten on every run)
    hours_cumulative: bool = True           # True = running total of hours;  False = hours on each day
    cards_cumulative: bool = True           # True = running total of new Anki cards;  False = per day
    width_px: int = 780
    height_px: int = 340
    gap_px: int = 20
    line_width: int = 3
    column: int | None = None               # first column (0 = A) of the charts; None = right after the log table


@dataclass(frozen=True)
class ConsoleSettings:
    bidi_fix: bool = True                   # reorder Hebrew for terminals without right-to-left support
    pause_on_exit: bool = True              # "Press Enter to exit" when run interactively


@dataclass(frozen=True)
class Settings:
    calendar: CalendarSettings = field(default_factory=CalendarSettings)
    reports: ReportSettings = field(default_factory=ReportSettings)
    sheet: SheetSettings = field(default_factory=SheetSettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    charts: ChartSettings = field(default_factory=ChartSettings)
    console: ConsoleSettings = field(default_factory=ConsoleSettings)


# ----------------------------------------------------------------------------
# Value converters (TOML gives dates / strings / lists; we want exact types)
# ----------------------------------------------------------------------------
_TIME_OF_DAY_RE = re.compile(r"\s*(\d{1,2})(?::(\d{2}))?\s*")
_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def parse_time_of_day(text: str) -> dtime:
    """'5', '05', '4:30', '05:30' -> time (24-hour clock).  Raises ValueError."""
    match = _TIME_OF_DAY_RE.fullmatch(text)
    if not match or int(match[1]) > 23 or int(match[2] or 0) > 59:
        raise ValueError(f"{text!r} - use an hour 0-23 in 24-hour format, e.g. 5 or 04:30")
    return dtime(int(match[1]), int(match[2] or 0))


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            raise ValueError("write the time as shown in the chat export, without a UTC offset")
        return value
    if isinstance(value, date):
        return datetime.combine(value, dtime(0, 0))
    return datetime.fromisoformat(str(value).strip())


def _as_time(value: Any) -> dtime:
    return value if isinstance(value, dtime) else parse_time_of_day(str(value))


def _as_optional_text(value: Any) -> str | None:
    return str(value).strip() or None


def _as_text_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of strings")
    return tuple(str(item) for item in value)


def _as_activities(value: Any) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("expected a table of  activity = [words...]")
    return {str(name): _as_text_tuple(words) for name, words in value.items()}


def _choice(*options: str) -> Callable[[Any], str]:
    def convert(value: Any) -> str:
        if value not in options:
            raise ValueError(f"must be one of {', '.join(options)}")
        return value
    return convert


def _hex_color(value: Any) -> str:
    if not isinstance(value, str) or not _HEX_COLOR_RE.fullmatch(value):
        raise ValueError("use a colour like #34A853")
    return value


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("must be a whole number, 1 or more")
    return value


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("must be a whole number, 0 or more")
    return value


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("must be true or false")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be non-empty text")
    return value


def _build(cls, table: Mapping[str, Any], section: str, converters: Mapping[str, Callable[[Any], Any]]):
    """Build one settings object from its TOML table, rejecting unknown keys and bad values."""
    if not isinstance(table, Mapping):
        raise ConfigError(f"config: [{section}] must be a table")
    known = [f.name for f in fields(cls)]
    unknown = sorted(set(table) - set(known))
    if unknown:
        raise ConfigError(f"config: unknown key(s) in [{section}]: {', '.join(unknown)}  (known: {', '.join(known)})")
    values = {}
    for key, value in table.items():
        try:
            values[key] = converters[key](value) if key in converters else value
        except (ValueError, TypeError) as error:
            raise ConfigError(f"config: bad value for {key} in [{section}]: {value!r} ({error})") from None
    return cls(**values)


def settings_from_table(table: Mapping[str, Any]) -> Settings:
    """Settings from an already-parsed TOML document."""
    sections = {"calendar", "reports", "sheet", "appearance", "charts", "console"}
    unknown = sorted(set(table) - sections)
    if unknown:
        raise ConfigError(f"config: unknown section(s): {', '.join(unknown)}  (known: {', '.join(sorted(sections))})")

    settings = Settings(
        calendar=_build(CalendarSettings, table.get("calendar", {}), "calendar", {
            "week_starts_on": _text, "day_1_weekday": _text, "day_1_date": _as_date,
            "skip_until_week": _non_negative_int, "skip_first_days": _non_negative_int,
            "timezone": _text, "chat_timezone": _text,
            "day_ends_at": _as_time, "format_start": _as_datetime}),
        reports=_build(ReportSettings, table.get("reports", {}), "reports", {
            "activities": _as_activities, "anki_words": _as_text_tuple,
            "rounding": _choice("floor", "round", "ceil"),
            "multiple_reports": _choice("last", "sum", "max")}),
        sheet=_build(SheetSettings, table.get("sheet", {}), "sheet", {
            "worksheet": _text, "log_worksheet": _as_optional_text, "week_table_name_regex": _text,
            "header_marker": _text, "weekday_labels": _as_text_tuple}),
        appearance=_build(AppearanceSettings, table.get("appearance", {}), "appearance", {
            "green": _hex_color, "red": _hex_color, "overwrite_filled_cells": _boolean}),
        charts=_build(ChartSettings, table.get("charts", {}), "charts", {
            "enabled": _boolean, "data_worksheet": _text,
            "hours_cumulative": _boolean, "cards_cumulative": _boolean,
            "width_px": _positive_int, "height_px": _positive_int, "gap_px": _non_negative_int,
            "line_width": _positive_int, "column": _non_negative_int}),
        console=_build(ConsoleSettings, table.get("console", {}), "console", {
            "bidi_fix": _boolean, "pause_on_exit": _boolean}),
    )

    if len(settings.sheet.weekday_labels) != 7:
        raise ConfigError("config: [sheet] weekday_labels needs exactly 7 labels, Monday first")
    if settings.sheet.log_worksheet and normalize_name(settings.sheet.log_worksheet) == normalize_name(settings.sheet.worksheet):
        raise ConfigError(f"config: log_worksheet ({settings.sheet.log_worksheet!r}) is the same tab as worksheet - "
                          f"the log needs its own tab. Give it another name or leave it empty.")
    return settings


def load_settings(path: Path | None) -> Settings:
    """Defaults, overridden by the TOML file at `path` (None = defaults only)."""
    if path is None:
        return Settings()
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path.name}: {error}") from None
    return settings_from_table(table)
