"""Calendar logic: which immersion day a moment belongs to, week-table rows, time-zone conversion.

A day does not end at midnight: it runs until ``day_ends_at`` (in the configured time zone) the next morning.
Until then it can still be reported and gets no red cross; from that moment an empty day turns red.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError, TrackerError
from .settings import CalendarSettings

WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def weekday_number(name: str) -> int:
    """'monday' -> 0 ... 'sunday' -> 6"""
    try:
        return WEEKDAY_NAMES.index(name.strip().lower())
    except ValueError:
        raise ConfigError(f"Bad weekday {name!r} in config - use one of {', '.join(WEEKDAY_NAMES)}.") from None


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise TrackerError(f"No time zone data for {name!r} - run:  pip install tzdata   "
                           f"(or check the name in config.toml)") from None


class Calendar:
    """Everything date-related, built from the [calendar] settings."""

    def __init__(self, settings: CalendarSettings):
        self.settings = settings
        self.timezone = settings.timezone
        self.chat_timezone = settings.chat_timezone or settings.timezone
        self.day_ends_at = settings.day_ends_at
        self.week_start_weekday = weekday_number(settings.week_starts_on)
        self.day_1_weekday = weekday_number(settings.day_1_weekday)
        self._zone = get_zone(self.timezone)
        self._chat_zone = get_zone(self.chat_timezone)

    # --- week tables --------------------------------------------------------
    def row_in_week_table(self, day: date) -> int:
        """Which row (0-6) of a week table this date sits in."""
        return (day.weekday() - self.week_start_weekday) % 7

    def week1_first_row_date(self, day1: date) -> date:
        """Date of the first row of the week-1 table (may be before Day #1)."""
        return day1 - timedelta(days=self.row_in_week_table(day1))

    def skip_days_until_week(self, day1: date, week: int | None) -> int:
        """How many days from Day #1 until the first row of week-table number `week` (0 for week 1)."""
        if not week or week <= 1:
            return 0
        first_row_of_week = self.week1_first_row_date(day1) + timedelta(days=7 * (week - 1))
        return max(0, (first_row_of_week - day1).days)

    def expected_weekday_labels(self, labels_monday_first: tuple[str, ...]) -> list[str]:
        """The 7 row labels a week table should have, in order."""
        return [labels_monday_first[(self.week_start_weekday + i) % 7] for i in range(7)]

    def skip_days(self, day1: date, cli_skip_first: int | None = None, cli_skip_until_week: int | None = None) -> int:
        """How many days from Day #1 are left untouched.  Priority: --skip-first, --skip-until-week,
        then skip_first_days, then skip_until_week from the config."""
        if cli_skip_first is not None:
            return max(0, cli_skip_first)
        if cli_skip_until_week is not None:
            return self.skip_days_until_week(day1, cli_skip_until_week)
        if self.settings.skip_first_days is not None:
            return max(0, self.settings.skip_first_days)
        return self.skip_days_until_week(day1, self.settings.skip_until_week)

    # --- days & time zones --------------------------------------------------
    def immersion_day(self, moment: datetime) -> date:
        """The immersion day a moment belongs to: Saturday 02:00 still belongs to Friday,
        Saturday 05:00 (with the default cutoff) already belongs to Saturday."""
        day = moment.date()
        return day if moment.time() >= self.day_ends_at else day - timedelta(days=1)

    def now(self) -> datetime:
        """The current moment in the configured time zone, whatever time zone this computer is set to."""
        return datetime.now(self._zone)

    def chat_to_local(self, moment: datetime) -> datetime:
        """A time as written in the chat export -> the wall-clock time in the configured zone (naive).
        The time zone database knows the daylight-saving dates, so Tokyo -> Israel is -7 h or -6 h as appropriate."""
        return moment.replace(tzinfo=self._chat_zone).astimezone(self._zone).replace(tzinfo=None)

    @property
    def format_start_local(self) -> datetime | None:
        """settings.format_start (written in chat time) converted to the configured zone."""
        start = self.settings.format_start
        return self.chat_to_local(start) if start else None
