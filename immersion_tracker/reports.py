"""Finding a student's daily summary in a chat message.

Report format (a number without a unit counts as minutes; missing lines = 0).
The day's time is the sum of the four activities; the Anki card count is only recorded in the log tab:

    סיכום יום 50                  (a ":" after the number is optional:  סיכום יום 50:)
    צפייה 10 דקות                 (יוטיוב counts as צפייה - it is logged under צפייה)
    קריאה 10 דקות
    שמיעה 10 דקות                 (שמיעה פסיבית counts as שמיעה)
    רילז 10 דקות
    אנקי 20 קלפים                 (optional: number of Anki cards, not part of the time)
    הטיות 40                      (optional: number of conjugation exercises, no unit needed; kept in its own tab)

Any other line is ignored - but if it looks like it might carry data (it has a number, or mentions an
activity), a warning says so, so a typo like "קריאת 20" can't silently cost someone their circle.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Mapping, Sequence

from .durations import parse_card_count, parse_duration, parse_item_count

if TYPE_CHECKING:
    from .whatsapp import Message

# "סיכום יום 50" / "יום 50" / "יום #50"
DAY_LINE_RE = re.compile(r"^\s*(?:סיכום\s+)?יום\s*(?:מספר\s*)?[#:\-–]?\s*(\d+)\s*:?", re.M)
# ^ "סיכום יום 50" / "סיכום יום 50:" / "סיכום יום: 50" / "סיכום יום מספר 50"
SUMMARY_HEADER_RE = re.compile(r"^\s*סיכום\s+יום", re.M)
MAX_DAY_NUMBER = 3650           # anything above is a typo (and would overflow the date arithmetic)
CONJUGATION_UNIT_WORDS = ("תרגילים", "תרגיל")      # may follow / precede the number, next to the line's own words
HINT_WORDS = ("שעה", "שעות", "דקות", "דקה", "קלפים", "קלף")    # a line mentioning these may carry data


def _alias_pattern(word: str) -> str:
    return re.escape(word).replace(r"\ ", r"\s+")


@dataclass
class Report:
    sent_at: datetime
    day_number: int | None              # from the "סיכום יום N" line, None if missing
    minutes_by_activity: dict[str, int]
    anki_cards: int | None              # None = no Anki line in the report
    notes: list[str] = field(default_factory=list)    # minor problems; the report is still used
    conjugations: int | None = None     # None = no conjugations line in the report

    @property
    def total_minutes(self) -> int:
        return sum(self.minutes_by_activity.values())


class ReportParser:
    """Recognises reports, given the activity names / aliases and the Anki words from the settings."""

    def __init__(self, activities: Mapping[str, Sequence[str]], anki_words: Sequence[str],
                 conjugation_words: Sequence[str] = ()):
        # One regex per activity: the line starts with one of its words (longest first, so
        # "שמיעה פסיבית" isn't mistaken for "שמיעה"), the rest of the line is the duration.
        self.activity_line_res = {
            activity: re.compile(
                rf"^\s*({'|'.join(_alias_pattern(w) for w in sorted(words, key=len, reverse=True))})\b\s*[:=\-–—]?\s*(.*)$")
            for activity, words in activities.items()
        }
        self.anki_line_re = re.compile(
            rf"^\s*(?:{'|'.join(map(re.escape, anki_words))})\b\s*[:=\-–—]?\s*(.*)$", re.I | re.M)
        self.conjugation_words = tuple(conjugation_words)
        self.conjugation_unit_words = self.conjugation_words + CONJUGATION_UNIT_WORDS
        self.conjugation_line_re = (re.compile(
            rf"^\s*(?:{'|'.join(_alias_pattern(w) for w in sorted(self.conjugation_words, key=len, reverse=True))})"
            rf"\b\s*[:=\-–—]?\s*(.*)$", re.M) if self.conjugation_words else None)
        self.hint_words = tuple(w.casefold() for w in (
            *(alias for aliases in activities.values() for alias in aliases), *anki_words,
            *self.conjugation_words, *HINT_WORDS))

    def _ignored_data_lines(self, text: str) -> list[str]:
        """Lines of a report that nothing recognised but that may carry data (a number, or an activity word):
        a free-text comment, or a typo in an activity name.  Blank and harmless lines are not worth a warning."""
        found = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if (DAY_LINE_RE.match(line) or SUMMARY_HEADER_RE.match(line) or self.anki_line_re.search(line)
                    or (self.conjugation_line_re and self.conjugation_line_re.search(line))
                    or any(regex.match(line) for regex in self.activity_line_res.values())):
                continue
            if any(char.isdigit() for char in stripped) or any(word in stripped.casefold() for word in self.hint_words):
                found.append(stripped)
        return found
    def extract(self, message: "Message") -> tuple[Report | None, str | None]:
        """-> (report, None)  |  (None, description of the problem)  |  (None, None) for ordinary chat."""
        text = re.sub(r"[*_~]", "", message.text)           # WhatsApp bold / italic / strike marks
        day_match = DAY_LINE_RE.search(text)
        day_number = int(day_match.group(1)) if day_match else None
        notes: list[str] = []
        if day_number is not None and day_number > MAX_DAY_NUMBER:
            notes.append(f"the day number {str(day_number)[:12]}... is not a real day number - ignored, "
                         f"the day the message was sent is used instead")
            day_number = None

        # activity -> raw duration text of each of its lines.  Different names of one activity
        # ("שמיעה" + "שמיעה פסיבית") are all kept and added up; a repeated name counts once (first wins).
        raw_durations: dict[str, list[str]] = {}
        seen_lines: set[tuple[str, str]] = set()
        for line in text.splitlines():
            for activity, regex in self.activity_line_res.items():
                match = regex.match(line)
                if not match:
                    continue
                key = (activity, " ".join(match.group(1).split()))
                if key not in seen_lines:
                    seen_lines.add(key)
                    raw_durations.setdefault(activity, []).append(match.group(2))
                break
        anki_match = self.anki_line_re.search(text)
        conjugation_match = self.conjugation_line_re.search(text) if self.conjugation_line_re else None
        lines_found = len(raw_durations) + (1 if anki_match else 0) + (1 if conjugation_match else 0)

        # Enough lines to be a report and not just chatter?
        if lines_found >= 3 or (lines_found >= 1 and day_match):
            minutes_by_activity: dict[str, int] = {}
            for activity, raw_list in raw_durations.items():
                parts = [parse_duration(raw) for raw in raw_list]
                for raw, minutes in zip(raw_list, parts):
                    if minutes is None:
                        return None, f"couldn't read the {activity} duration {raw.strip()!r}"
                minutes_by_activity[activity] = sum(parts)
            anki_cards = None
            if anki_match:
                anki_cards = parse_card_count(anki_match.group(1))
                if anki_cards is None:      # the card count isn't part of the time, so don't throw the report away
                    notes.append(f"couldn't read the Anki card count {anki_match.group(1).strip()!r} "
                                 f"- report used, card count left empty")
            conjugations = None
            if conjugation_match:
                conjugations = parse_item_count(conjugation_match.group(1), self.conjugation_unit_words)
                if conjugations is None:
                    notes.append(f"couldn't read the conjugations count {conjugation_match.group(1).strip()!r} "
                                 f"- report used, conjugations left empty")
            for line in self._ignored_data_lines(text):
                notes.append(f"ignored a line that isn't a report line (not counted): {line[:80]!r}")
            return Report(message.sent_at, day_number, minutes_by_activity, anki_cards, notes, conjugations), None

        if lines_found == 2:
            return None, "looks like an immersion report but has no 'סיכום יום N' line"
        if SUMMARY_HEADER_RE.search(text):
            return None, "has a 'סיכום יום' line but no activity lines"
        return None, None


def circle_count(minutes: int, rounding: str = "floor") -> int:
    """Number of ◯ for a day's minutes (any immersion at all gives at least one)."""
    if minutes <= 0:
        return 0
    hours = minutes / 60
    count = {"floor": math.floor(hours), "round": math.floor(hours + 0.5), "ceil": math.ceil(hours)}[rounding]
    return max(1, count)


@dataclass
class DayTotals:
    """One student's immersion on one day (after merging multiple reports)."""
    minutes_by_activity: dict[str, int]
    anki_cards: int | None
    total_minutes: int
    conjugations: int | None = None


def merge_reports(reports: list[Report], mode: str = "last") -> DayTotals:
    """Combine several reports for the same student+day according to `mode` ("last", "sum", "max")."""
    if mode == "sum":
        minutes_by_activity: dict[str, int] = defaultdict(int)
        for report in reports:
            for activity, minutes in report.minutes_by_activity.items():
                minutes_by_activity[activity] += minutes
        card_counts = [r.anki_cards for r in reports if r.anki_cards is not None]
        conjugation_counts = [r.conjugations for r in reports if r.conjugations is not None]
        return DayTotals(dict(minutes_by_activity), sum(card_counts) if card_counts else None,
                         sum(r.total_minutes for r in reports),
                         sum(conjugation_counts) if conjugation_counts else None)
    chosen = max(reports, key=lambda r: r.total_minutes) if mode == "max" else reports[-1]
    return DayTotals(dict(chosen.minutes_by_activity), chosen.anki_cards, chosen.total_minutes, chosen.conjugations)
