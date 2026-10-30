"""Interactive ``--setup``: go through everyone in the chat and mark them as a student (+ sheet column) or ignored."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Callable

from .people import People
from .reports import ReportParser
from .sheets.client import OpenSheet
from .sheets.week_tables import load_week_blocks
from .settings import SheetSettings
from .textutil import normalize_name
from .timeline import Calendar
from .whatsapp import Message


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"


def read_sheet_headers(open_sheet: OpenSheet, sheet: SheetSettings, calendar: Calendar) -> list[str] | None:
    """Student column headers of the first week table (to pick from during --setup)."""
    try:
        spreadsheet, worksheet = open_sheet()
        blocks = load_week_blocks(spreadsheet, worksheet, None, sheet, calendar)
        return blocks[min(blocks)].column_names if blocks else None
    except Exception as error:      # missing key file, no access, gspread not installed...
        print(f"(couldn't read the sheet: {error}\n you'll type column names by hand)")
        return None


def pick_sheet_column(headers: list[str] | None, people: People) -> str | None:
    """Ask which sheet column a student belongs to. Returns None if cancelled."""
    names_by_column: dict[str, list[str]] = defaultdict(list)
    for whatsapp_name, column in people.students.items():
        names_by_column[normalize_name(column)].append(whatsapp_name)
    if headers:
        print("  Sheet columns:")
        for number, header in enumerate(headers, 1):
            taken_by = names_by_column.get(normalize_name(header))
            note = f"   (already: {', '.join(taken_by)})" if taken_by else ""
            print(f"   {number:2d}. {header}{note}")

    while True:
        answer = ask("  Column number" + (" or name" if headers else " / name") + " (Enter = cancel): ")
        if not answer or answer.lower() == "q":
            return None
        if headers and answer.isdigit() and 1 <= int(answer) <= len(headers):
            return headers[int(answer) - 1]
        if headers:
            matches = [h for h in headers if normalize_name(h) == normalize_name(answer)]
            if matches:
                return matches[0]
            if ask(f"  '{answer}' isn't a column in the sheet. Use it anyway? [y/N] ").lower() != "y":
                continue
        return answer


def setup_people(messages: list[Message], people: People, parser: ReportParser, revisit_all: bool,
                 read_headers: Callable[[], list[str] | None]) -> None:
    """Go through everyone in the chat and mark them as student (+ column) or ignored."""
    message_counts: Counter = Counter()
    report_counts: Counter = Counter()
    display_names: dict[str, str] = {}
    last_first_line: dict[str, str] = {}
    for message in messages:
        if not message.sender:
            continue
        key = normalize_name(message.sender)
        message_counts[key] += 1
        display_names.setdefault(key, message.sender)
        if parser.extract(message)[0]:
            report_counts[key] += 1
        if message.text.strip():
            last_first_line[key] = message.text.strip().splitlines()[0][:70]

    student_keys = {normalize_name(name): column for name, column in people.students.items()}
    ignored_keys = people.ignored_keys()
    to_review = [key for key, _ in message_counts.most_common()
                 if revisit_all or (key not in student_keys and key not in ignored_keys)]
    if not to_review:
        print("Everyone in the chat is already classified. (Use --setup --all to change someone.)")
        return

    headers = read_headers()
    print(f"\n{len(to_review)} people to go through.  For each:  s = student   i = ignore   "
          f"Enter = skip for now   q = quit\n(progress is saved after every answer)")
    for key in to_review:
        name = display_names[key]
        current = (f"student -> {student_keys[key]}" if key in student_keys
                   else "ignored" if key in ignored_keys else None)
        print(f"\n--- {name}")
        print(f"    {message_counts[key]} messages, {report_counts[key]} look like immersion reports")
        if key in last_first_line:
            print(f"    last message: {last_first_line[key]!r}")
        if current:
            print(f"    currently: {current}")
        choice = ask("    [s]tudent / [i]gnore / Enter = " + ("keep" if current else "skip") + " / [q]uit: ").lower()
        if choice == "q":
            break
        if choice == "i":
            people.forget(key)
            people.ignored.add(name)
        elif choice == "s":
            column = pick_sheet_column(headers, people)
            if column is None:
                continue
            people.forget(key)
            people.students[name] = column
        else:
            continue
        people.save()
        print("    saved.")

    classified = {normalize_name(n) for n in people.students} | people.ignored_keys()
    unclassified = [display_names[key] for key in message_counts if key not in classified]
    if headers:
        used_columns = {normalize_name(c) for c in people.students.values()}
        unused = [h for h in headers if normalize_name(h) not in used_columns]
        if unused:
            print(f"\nSheet columns with nobody assigned yet: {', '.join(unused)}")
    if unclassified:
        print(f"Still unclassified: {', '.join(unclassified)}")
    print(f"\nSaved to {people.path}")
