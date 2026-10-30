"""From chat messages to a plan of what goes into every (student, day) cell of the sheet."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Sequence

from .console import print_table
from .people import People
from .reports import DayTotals, Report, ReportParser, circle_count, merge_reports
from .settings import AppearanceSettings, ReportSettings
from .textutil import normalize_name
from .timeline import WEEKDAY_SHORT, Calendar
from .whatsapp import Message, message_stamp

Warn = Callable[..., None]      # warn(text, about_date=None)


@dataclass
class FoundReport:
    sheet_column: str       # the student's column header in the sheet
    message: Message
    report: Report


@dataclass
class SheetCell:
    text: str
    green: bool             # True = green background, False = red


def gather_reports(messages: list[Message], people: People, parser: ReportParser,
                   calendar: Calendar, warn: Warn) -> list[FoundReport]:
    """Every valid report from a known student, in chat order."""
    column_by_sender = people.column_by_sender()
    ignored = people.ignored_keys()
    unknown_senders: Counter = Counter()
    found: list[FoundReport] = []

    format_start = calendar.format_start_local
    if format_start:
        shown_start = calendar.settings.format_start
        print(f"Messages before {shown_start:%Y-%m-%d %H:%M} {calendar.chat_timezone} "
              f"({format_start:%Y-%m-%d %H:%M} {calendar.timezone}) are treated as old-format and not read "
              f"(format_start)")
    for message in messages:
        if message.sender is None:
            continue
        if format_start and message.sent_at < format_start:
            continue
        sender_key = normalize_name(message.sender)
        if sender_key in ignored:
            continue
        if sender_key not in column_by_sender:
            unknown_senders[message.sender] += 1
            continue

        report, problem = parser.extract(message)
        if problem:
            first_line = message.text.strip().splitlines()[0][:60] if message.text.strip() else ""
            warn(f"{message_stamp(message)} {message.sender}: {problem}  [{first_line}]",
                 calendar.immersion_day(message.sent_at))
        if report:
            for note in report.notes:
                warn(f"{message_stamp(message)} {message.sender}: {note}", calendar.immersion_day(message.sent_at))
            found.append(FoundReport(column_by_sender[sender_key], message, report))

    for name, count in unknown_senders.most_common():
        warn(f"sender not classified: {name!r} ({count} messages) - run with --setup", None)
    print(f"Found {len(found)} valid reports")
    return found


def infer_day1(found: list[FoundReport], calendar: Calendar) -> date | None:
    """Day 1 = the day_1_weekday that most reports agree on.

    A report for Day N sent on date X (same day, or up to 2 days late) implies
    Day 1 = X - (N-1) - late.  Only candidates on the right weekday get a vote, so
    a late poster can't pull the answer off by one day.
    """
    votes: Counter = Counter()
    for item in found:
        if item.report.day_number is None:
            continue
        for days_late in range(3):
            candidate = calendar.immersion_day(item.message.sent_at) - timedelta(days=item.report.day_number - 1 + days_late)
            if candidate.weekday() == calendar.day_1_weekday:
                votes[candidate] += 1
                break
    return votes.most_common(1)[0][0] if votes else None


def collect_day_totals(found: list[FoundReport], day1: date, first_day_to_write: date, today: date,
                       calendar: Calendar, multiple_reports: str, warn: Warn) -> dict[tuple[str, date], DayTotals]:
    """Group reports by (sheet column, date).  Days before first_day_to_write are dropped silently."""
    reports_by_cell: dict[tuple[str, date], list[Report]] = defaultdict(list)
    for item in found:
        message, report = item.message, item.report
        who = f"{message_stamp(message)} {message.sender}"
        sent_day = calendar.immersion_day(message.sent_at)      # a message before day_ends_at still belongs to the previous day

        if report.day_number is not None:
            report_date = day1 + timedelta(days=report.day_number - 1)
            if report_date >= first_day_to_write and abs((report_date - sent_day).days) > 1:
                warn(f"{who}: says Day #{report.day_number} = {report_date}, "
                     f"but was sent on {sent_day}", report_date)
        else:
            report_date = sent_day
            if report_date >= first_day_to_write:
                warn(f"{who}: no day number, counted as {report_date} "
                     f"(the day it was sent in - days end at {calendar.day_ends_at:%H:%M} {calendar.timezone})", report_date)

        if report_date < first_day_to_write:
            if report_date < day1:
                warn(f"{who}: report is for {report_date}, before Day 1 - ignored", report_date)
            continue    # inside the skipped first days: leave alone
        if report_date > today:
            warn(f"{who}: report is for {report_date}, which is in the future (typo in the day number?)",
                 report_date)
        reports_by_cell[(item.sheet_column, report_date)].append(report)

    return {cell: merge_reports(reports, multiple_reports) for cell, reports in reports_by_cell.items()}


def build_plan(day_totals: dict[tuple[str, date], DayTotals], columns: Sequence[str], first_day_to_write: date,
               today: date, reports: ReportSettings, appearance: AppearanceSettings) -> dict[tuple[str, date], SheetCell]:
    """Decide what goes in every (student column, date) cell, from first_day_to_write up to today.
    `today` is the day in progress (see Calendar.immersion_day): it ends at day_ends_at, not at midnight."""
    last_day = max([today] + [day for _, day in day_totals])

    plan: dict[tuple[str, date], SheetCell] = {}
    day = first_day_to_write
    while day <= last_day:
        for column in columns:
            totals = day_totals.get((column, day))
            circles = circle_count(totals.total_minutes, reports.rounding) if totals else 0
            if circles:
                plan[(column, day)] = SheetCell(appearance.circle * circles, green=True)
            elif day < today:       # the day is over (day_ends_at has passed) and nothing was reported
                plan[(column, day)] = SheetCell(appearance.cross, green=False)
            # else: the day in progress / future with nothing reported yet -> leave the cell alone
        day += timedelta(days=1)
    return plan


def print_plan(plan: dict[tuple[str, date], SheetCell], columns: Sequence[str], day1: date,
               first_day_to_write: date, calendar: Calendar) -> None:
    """Preview of what will be written, one table per week ('-' = not touched, '.' = left alone)."""
    if not plan:
        print("Nothing to write.")
        return
    week1_start = calendar.week1_first_row_date(day1)
    first_week = (first_day_to_write - week1_start).days // 7
    last_week = (max(day for _, day in plan) - week1_start).days // 7

    for week in range(first_week, last_week + 1):
        days = [week1_start + timedelta(days=7 * week + i) for i in range(7)]
        headers = ["תלמיד"] + [f"{WEEKDAY_SHORT[d.weekday()]} {d:%d/%m}" for d in days]
        rows = []
        for column in columns:
            row = [column]
            for d in days:
                if d < first_day_to_write:
                    row.append("-")
                else:
                    cell = plan.get((column, d))
                    row.append(cell.text if cell else ".")
            rows.append(row)
        print(f"\n=== week {week + 1} ===")
        print_table(headers, rows)
