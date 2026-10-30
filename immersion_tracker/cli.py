"""Command line interface: ``python main.py <chat export> [options]``."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Sequence

from . import __version__
from .console import install_console_bidi_fix, use_utf8_output
from .credentials import load_credentials, load_dotenv
from .errors import TrackerError
from .paths import CONFIG_FILE, ENV_FILE, PEOPLE_FILE, project_root
from .people import People
from .planning import build_plan, collect_day_totals, gather_reports, infer_day1, print_plan
from .reports import ReportParser
from .settings import Settings, load_settings, parse_time_of_day
from .setup_wizard import read_sheet_headers, setup_people
from .sheets.charts import print_chart_colors, write_charts
from .sheets.client import make_sheet_opener
from .sheets.log import build_log_rows, log_columns, print_last_day_per_student, print_log, write_log
from .sheets.week_tables import read_snapshot, sheet_order, write_week_tables
from .textutil import normalize_name
from .timeline import WEEKDAY_SHORT, Calendar
from .whatsapp import parse_chat


def parse_cutoff(text: str):
    """--cutoff value: the hour the day ends, 24-hour clock - '5', '05', '4:30', '05:30'."""
    try:
        return parse_time_of_day(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def parse_now(text: str) -> datetime:
    """--today value: '2026-10-30' (taken as noon that day) or '2026-10-30 04:30'."""
    try:
        moment = datetime.fromisoformat(text.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} - use YYYY-MM-DD or 'YYYY-MM-DD HH:MM'") from None
    return moment.replace(hour=12) if len(text.strip()) <= 10 else moment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="immersion-tracker",
        description="Update the immersion sheet from a WhatsApp export.")
    parser.add_argument("chat", type=Path, help="WhatsApp export (.txt or .zip)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    modes = parser.add_argument_group("modes")
    modes.add_argument("--setup", action="store_true", help="interactively classify people (student / ignore)")
    modes.add_argument("--all", action="store_true", help="with --setup: also go through people already classified")
    modes.add_argument("--list-senders", action="store_true", help="list everyone who posted, then exit")
    modes.add_argument("--dry-run", action="store_true", help="show what would be written, don't touch the sheet")
    modes.add_argument("--offline", action="store_true",
                       help="don't contact Google at all (implies --dry-run; students are shown in people.json order)")

    days = parser.add_argument_group("days")
    days.add_argument("--day1", type=date.fromisoformat, metavar="DATE",
                      help="date of Day #1, YYYY-MM-DD (overrides day_1_date)")
    days.add_argument("--skip-first", type=int, metavar="N", help="leave Day 1..N untouched (overrides the config)")
    days.add_argument("--skip-until-week", type=int, metavar="N",
                      help="leave everything before the first row of week N untouched (overrides skip_until_week)")
    days.add_argument("--today", type=parse_now, metavar="WHEN",
                      help="pretend it is now: YYYY-MM-DD (noon) or 'YYYY-MM-DD HH:MM', in the configured time zone")
    days.add_argument("--cutoff", type=parse_cutoff, metavar="HOUR",
                      help="hour the day ends, 24-hour clock, e.g. 5 or 04:30 (overrides day_ends_at)")
    days.add_argument("--date-order", choices=["auto", "DMY", "MDY", "YMD"], default="auto",
                      help="how dates in the export are written (default: guess)")

    output = parser.add_argument_group("output")
    output.add_argument("--overwrite", action="store_true",
                        help="also overwrite sheet cells that already hold ◯ / ✖ (default: leave them alone)")
    output.add_argument("--raw-hebrew", action="store_true",
                        help="print Hebrew in plain logical order (for terminals that handle Hebrew themselves)")
    output.add_argument("--no-pause", action="store_true", help="don't wait for Enter at the end")

    files = parser.add_argument_group("files")
    files.add_argument("--config", type=Path, metavar="FILE", help=f"settings file (default: {CONFIG_FILE} if present)")
    files.add_argument("--people", type=Path, metavar="FILE", help=f"who is a student (default: {PEOPLE_FILE})")
    return parser


def run(args: argparse.Namespace) -> Settings:
    """Everything the tool does for one invocation.  Raises TrackerError for expected problems."""
    use_utf8_output()
    root = project_root()
    load_dotenv(root / ENV_FILE)

    # --- settings
    config_path = args.config or (root / CONFIG_FILE if (root / CONFIG_FILE).is_file() else None)
    settings = load_settings(config_path)
    if args.cutoff is not None:
        settings = replace(settings, calendar=replace(settings.calendar, day_ends_at=args.cutoff))
    if settings.console.bidi_fix and not args.raw_hebrew:
        install_console_bidi_fix()
    if config_path is None:
        print(f"(no {CONFIG_FILE} found - using the built-in defaults; copy config.example.toml to make your own)")

    calendar = Calendar(settings.calendar)
    people = People.load(args.people or root / PEOPLE_FILE)
    parser = ReportParser(settings.reports.activities, settings.reports.anki_words)
    messages = parse_chat(args.chat, calendar, args.date_order)

    now = args.today or calendar.now()
    today = calendar.immersion_day(now)      # the day in progress: it only ends at day_ends_at

    # --- the helper modes
    if args.list_senders:
        known = {normalize_name(n) for n in people.students} | people.ignored_keys()
        for name, count in Counter(m.sender for m in messages if m.sender).most_common():
            print(f"{count:6d}  {name}{'' if normalize_name(name) in known else '   <-- not classified'}")
        return settings

    open_sheet = make_sheet_opener(lambda: load_credentials(root), settings.sheet)
    if args.setup:
        setup_people(messages, people, parser, args.all,
                     lambda: read_sheet_headers(open_sheet, settings.sheet, calendar))
        return settings
    if not people.students:
        raise TrackerError("Nobody is set up as a student yet - run:  python main.py <chat> --setup")

    # --- read the sheet now: the order of its columns decides the order the students are listed in everywhere
    # (a dry run can do without it; a real run can't)
    dry_run = args.dry_run or args.offline
    snapshot = None
    if not args.offline:
        snapshot = read_snapshot(open_sheet, settings.sheet, calendar, required=not dry_run,
                                 fallback_note=f"students are shown in the order of {PEOPLE_FILE} instead of the order of the sheet)")
    columns = people.columns(sheet_order(snapshot.blocks) if snapshot and snapshot.blocks else ())

    # Warnings are collected first and printed at the end, so those that only concern
    # the skipped first days can be left out.  Each is (date it concerns or None, text).
    warnings: list[tuple[date | None, str]] = []

    def warn(text: str, about_date: date | None = None) -> None:
        warnings.append((about_date, text))

    found_reports = gather_reports(messages, people, parser, calendar, warn)

    # --- Day 1, and the first day we are allowed to write
    day1 = args.day1 or settings.calendar.day_1_date
    if day1 is None:
        day1 = infer_day1(found_reports, calendar)
        if day1 is None:
            raise TrackerError("Couldn't work out the date of Day #1 from the chat - "
                               "set day_1_date in config.toml or pass --day1 YYYY-MM-DD.")
        print(f"Day #1 auto-detected as {day1} ({WEEKDAY_SHORT[day1.weekday()]}) - "
              f"pin it with day_1_date or --day1 if that's wrong")
    elif day1.weekday() != calendar.day_1_weekday:
        warn(f"Day 1 ({day1}) is a {WEEKDAY_SHORT[day1.weekday()]}, but day_1_weekday is {settings.calendar.day_1_weekday!r}")

    skip_days = calendar.skip_days(day1, args.skip_first, args.skip_until_week)
    first_day_to_write = day1 + timedelta(days=skip_days)
    if skip_days:
        print(f"Leaving Day 1-{skip_days} untouched - writing from Day {skip_days + 1} ({first_day_to_write})")

    # --- build what to write
    print(f"Now: {now:%Y-%m-%d %H:%M} ({calendar.timezone}) -> current day is {today}; "
          f"days end at {calendar.day_ends_at:%H:%M}, so ✖ is given to days before {today}")
    day_totals = collect_day_totals(found_reports, day1, first_day_to_write, today, calendar,
                                    settings.reports.multiple_reports, warn)
    plan = build_plan(day_totals, columns, first_day_to_write, today, settings.reports, settings.appearance)

    shown_warnings = [text for about_date, text in warnings
                      if about_date is None or about_date >= first_day_to_write]
    if shown_warnings:
        print(f"\n--- {len(shown_warnings)} warning(s) ---")
        for text in shown_warnings:
            print(" *", text)

    log_title = settings.sheet.log_worksheet
    activities = list(settings.reports.activities)
    log_header = log_columns(activities)
    log_rows = build_log_rows(day_totals, day1, columns, activities) if log_title else []
    print_plan(plan, columns, day1, first_day_to_write, calendar)          # the table is shown on every run

    overwrite = args.overwrite or settings.appearance.overwrite_filled_cells
    if dry_run:
        if not overwrite:
            print("\n(when writing, cells that already hold ◯ / ✖ in the sheet are left untouched)")
        if log_rows:
            print_log(log_rows, log_title, log_header)
            if settings.charts.enabled:
                print_chart_colors(columns)
        return settings

    spreadsheet = write_week_tables(plan, day1, overwrite, snapshot, settings.sheet, settings.appearance, calendar)
    logged = write_log(spreadsheet, log_rows, log_title, columns, log_header) if log_rows else None
    if logged:
        log_worksheet, all_log_rows = logged
        print_last_day_per_student(log_rows, columns, log_header)
        if settings.charts.enabled:
            write_charts(spreadsheet, log_worksheet, all_log_rows, (today - day1).days + 1, columns,
                         settings.charts, len(log_header))
    return settings


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        settings = run(args)
    except TrackerError as error:
        sys.exit(str(error))
    except KeyboardInterrupt:
        sys.exit(130)
    if settings.console.pause_on_exit and not args.no_pause and sys.stdin is not None and sys.stdin.isatty():
        input("\nDone. Press Enter to exit.")      # keeps a double-clicked console window open
