"""Reading a WhatsApp chat export (.txt, or the .zip WhatsApp produces)."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from pathlib import Path

from .errors import TrackerError
from .textutil import strip_invisible_chars
from .timeline import Calendar


@dataclass
class Message:
    sent_at: datetime       # converted to the configured time zone (Israel) - used for everything (5AM rule, format_start...)
    sender: str | None      # None = system message
    text: str
    shown_at: datetime | None = None    # the time exactly as written in the export (chat time zone)


@dataclass
class RawMessage:
    """A message as found in the file, before dates/times are interpreted."""
    date_text: str
    time_text: str
    sender: str | None
    lines: list[str]


# Android: "12/03/2024, 14:35 - Name: text"     iOS: "[12/03/2024, 14:35:12] Name: text"
MESSAGE_START_RE = re.compile(
    r"^\[?(?P<date>\d{1,4}[./-]\d{1,2}[./-]\d{1,4}),?\s+"
    r"(?P<time>\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\s*[AaPp]\.?[Mm]\.?(?![A-Za-z]))?)\]?"
    r"\s*-?\s*(?P<rest>.*)$"
)
SENDER_AND_TEXT_RE = re.compile(r"^([^:]{1,80}?):(?:\s+(.*))?$")
TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\s*(?:([AaPp])\.?[Mm]\.?)?")


def message_stamp(message: Message) -> str:
    """'2026-10-30 08:58 (Israel 10-30 01:58)': the time as shown in the chat, then the converted time."""
    shown = message.shown_at or message.sent_at
    return f"{shown:%Y-%m-%d %H:%M} (Israel {message.sent_at:%m-%d %H:%M})"


def read_export(path: Path) -> str:
    """Contents of the chat export (.txt, or the first chat .txt inside a .zip)."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            txt_names = [n for n in archive.namelist() if n.lower().endswith(".txt")]
            if not txt_names:
                raise TrackerError("No .txt file found inside the zip.")
            txt_names.sort(key=lambda n: ("_chat" not in n.lower(), n))
            return archive.read(txt_names[0]).decode("utf-8-sig", errors="replace")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def detect_date_order(date_texts: list[str]) -> str:
    """Guess "DMY" / "MDY" / "YMD" from the dates in the chat."""
    first_part_over_12 = second_part_over_12 = False
    for date_text in date_texts:
        parts = re.split(r"[./-]", date_text)
        if len(parts[0]) == 4:
            return "YMD"
        first_part_over_12 |= int(parts[0]) > 12
        second_part_over_12 |= int(parts[1]) > 12
    if first_part_over_12:
        return "DMY"
    if second_part_over_12:
        return "MDY"
    return "DMY"    # ambiguous: override with --date-order if wrong


def parse_date(date_text: str, order: str) -> date:
    a, b, c = (int(part) for part in re.split(r"[./-]", date_text))
    if order == "YMD":
        year, month, day = a, b, c
    elif order == "MDY":
        month, day, year = a, b, c
    else:
        day, month, year = a, b, c
    if year < 100:
        year += 2000
    return date(year, month, day)


def parse_time(time_text: str) -> dtime:
    match = TIME_RE.match(time_text)
    hour, minute, second = int(match[1]), int(match[2]), int(match[3] or 0)
    am_pm = (match[4] or "").lower()
    if am_pm == "p" and hour < 12:
        hour += 12
    if am_pm == "a" and hour == 12:
        hour = 0
    return dtime(hour, minute, second)


def parse_chat(path: Path, calendar: Calendar, date_order: str = "auto") -> list[Message]:
    chat_text = strip_invisible_chars(read_export(path))

    # Pass 1: split the file into messages (a line without a date header continues the previous message).
    raw_messages: list[RawMessage] = []
    for line in chat_text.splitlines():
        header = MESSAGE_START_RE.match(line)
        if header:
            rest = header.group("rest")
            sender_match = SENDER_AND_TEXT_RE.match(rest)
            if sender_match:
                raw_messages.append(RawMessage(header["date"], header["time"],
                                               sender_match.group(1).strip(), [sender_match.group(2) or ""]))
            else:   # no "Name:" part -> system message
                raw_messages.append(RawMessage(header["date"], header["time"], None, [rest]))
        elif raw_messages:
            raw_messages[-1].lines.append(line)
    if not raw_messages:
        raise TrackerError("Couldn't find any WhatsApp messages in that file - is it a chat export?")

    # Pass 2: turn the date/time strings into real datetimes.
    order = detect_date_order([m.date_text for m in raw_messages]) if date_order == "auto" else date_order
    print(f"Parsed {len(raw_messages)} messages (date order: {order})")

    messages: list[Message] = []
    for raw in raw_messages:
        try:
            shown_at = datetime.combine(parse_date(raw.date_text, order), parse_time(raw.time_text))
        except (ValueError, TypeError):
            continue    # impossible date/time -> it wasn't really a message header
        messages.append(Message(calendar.chat_to_local(shown_at), raw.sender, "\n".join(raw.lines), shown_at))
    if messages:
        last = messages[-1]
        hours_behind = (last.shown_at - last.sent_at).total_seconds() / 3600
        print(f"Chat times are in {calendar.chat_timezone}; converted to {calendar.timezone} "
              f"(latest message: {hours_behind:g} h earlier) - days end at {calendar.day_ends_at:%H:%M} {calendar.timezone}")
    return messages
