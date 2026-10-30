"""Understanding the numbers in a report line: durations ("1 שעה ו-20 דקות") and Anki card counts.

Durations understood: 10 דקות, 1 שעה, 1 שעה ו-20 דקות, 1.5 שעות, 1:35, 90, 0 - a number without a unit is minutes.
Words work too (the "ו" / "ו-" in front is always optional):
    שעה = 60 דקות      רבע = 15 דקות      חצי = 30 דקות
    שעה ורבע = 75      שעה וחצי = 90      2 שעות וחצי = 150      חצי שעה = 30      רבע שעה = 15
"""
from __future__ import annotations

import re

# Duration pieces.  Units: שעה/שעות/ש = hours, דקה/דקות/ד = minutes.
_UNIT = r"(?:שעות|שעה|ש|דקות|דקה|ד)['’׳]?"
_NOT_FOLLOWED_BY_LETTER = r"(?![א-ת])"
_NUMBER = r"\d+(?:[.,]\d+)?"

SEPARATOR_RE = re.compile(r"\s*(?:[,&+]|ו-?)?\s*")                      # between two pieces
NUMBER_WITH_UNIT_RE = re.compile(rf"({_NUMBER})\s*({_UNIT}){_NOT_FOLLOWED_BY_LETTER}")   # 20 דקות / 1.5 שעות
FRACTION_WORD_RE = re.compile(rf"(רבע|חצי){_NOT_FOLLOWED_BY_LETTER}(?:\s+שעה{_NOT_FOLLOWED_BY_LETTER})?")
HOUR_WORD_RE = re.compile(rf"שעה{_NOT_FOLLOWED_BY_LETTER}")                # a lone "שעה" = 60 minutes
FRACTION_MINUTES = {"רבע": 15, "חצי": 30}
CLOCK_STYLE_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?!\d)")                 # 1:35
BARE_NUMBER_RE = re.compile(rf"({_NUMBER})\s*(?:\(.*\)|[-–—,;].*)?")       # 90  /  90 (note)
ZERO_WORDS_RE = re.compile(r"0+|-+|אין|כלום|לא")


def parse_duration(text: str) -> int | None:
    """'1 שעה ו-20 דקות' -> 80,  'שעה וחצי' -> 90.  Returns minutes, or None if it can't be understood."""
    text = text.strip().rstrip(".").strip()
    if not text:
        return None
    if ZERO_WORDS_RE.fullmatch(text):
        return 0

    bare = BARE_NUMBER_RE.fullmatch(text)          # no unit -> minutes
    if bare:
        return int(round(float(bare.group(1).replace(",", "."))))

    clock = CLOCK_STYLE_RE.match(text)
    if clock:
        return int(clock[1]) * 60 + int(clock[2])

    # Read pieces left to right: "1 שעה", "20 דקות", "שעה", "רבע", "חצי שעה"... and add them up.
    total_minutes = 0.0
    found_any = False
    pos = 0
    while True:
        pos = SEPARATOR_RE.match(text, pos).end()
        if match := NUMBER_WITH_UNIT_RE.match(text, pos):
            value = float(match[1].replace(",", "."))
            total_minutes += value * 60 if match[2][0] == "ש" else value
        elif match := FRACTION_WORD_RE.match(text, pos):
            total_minutes += FRACTION_MINUTES[match[1]]
        elif match := HOUR_WORD_RE.match(text, pos):
            total_minutes += 60
        else:
            break
        found_any = True
        pos = match.end()
    if not found_any:
        return None
    if text[pos:].lstrip()[:1].isdigit():     # "1 שעה 35": unit missing, don't guess
        return None
    return int(round(total_minutes))


# The Anki line is   אנקי 20 קלפים   - the word קלפים is optional (and may stand on either side of
# the number), a "+" after the number is fine, and anything after that (a note in parentheses...) is ignored.
_CARD_WORD = r"(?:קלפים|קלף|כרטיסיות|כרטיסיה|כרטיסים|כרטיס|cards?)"
CARD_COUNT_RE = re.compile(rf"^(?:{_CARD_WORD}\s*)?(\d[\d,]*)\+?(?![\d.])\s*(?:{_CARD_WORD})?", re.I)


def parse_card_count(text: str) -> int | None:
    """'120' / '20 קלפים' / '400+ קלפים' / 'קלפים 20' / '20 קלפים (=20 חדשים)' -> number of Anki cards,
    or None if the line doesn't start with a number."""
    text = text.strip().rstrip(".").strip()
    if ZERO_WORDS_RE.fullmatch(text):
        return 0
    match = CARD_COUNT_RE.match(text)
    return int(match.group(1).replace(",", "")) if match else None
