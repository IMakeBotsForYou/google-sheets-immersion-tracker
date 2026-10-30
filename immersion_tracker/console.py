"""Terminal output: tables, and a fix for Hebrew on consoles without right-to-left support.

A console without right-to-left support shows characters strictly left to right, so Hebrew has to
be handed to it already in *visual* order.  Every run of Hebrew (with the spaces / digits / punctuation
between its words) is reversed in place, numbers stay readable ("1:35", "20"), brackets inside the
run are mirrored.  Latin text and the " | " column separators of the tables stay where they are,
and the text keeps its length, so the table alignment is not affected.
"""
from __future__ import annotations

import re
import sys

_HEBREW = "\u0590-\u05ff"
_ATOM = rf"[{_HEBREW}\d \t\-–—'\"’,.:;!?+=/*#&%_~@]"          # may sit inside a Hebrew run
_GROUP = rf"[(\[]{_ATOM}*[)\]]"                                 # a whole "(...)" - only if it holds nothing but Hebrew-side text
_RTL_RUN_RE = re.compile(rf"[{_HEBREW}](?:(?:{_ATOM}|{_GROUP})*(?:[{_HEBREW}\d]|{_GROUP}))?")
_NUMBER_RE = re.compile(r"\d+(?:[:.,/]\d+)*")
_HEBREW_MARK_RE = re.compile(r"[\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]")   # niqqud / cantillation
_MIRRORED = str.maketrans("()[]{}<>", ")(][}{><")


def _reverse_run(run: str) -> str:
    clusters: list[str] = []
    for char in run:                                    # keep niqqud attached to its letter
        if clusters and _HEBREW_MARK_RE.match(char):
            clusters[-1] += char
        else:
            clusters.append(char)
    reversed_run = "".join(reversed(clusters)).translate(_MIRRORED)
    return _NUMBER_RE.sub(lambda number: number.group()[::-1], reversed_run)   # digits stay left-to-right


def visual_hebrew(text: str) -> str:
    """Re-order the Hebrew in `text` for a terminal that can't do right-to-left."""
    if not re.search(rf"[{_HEBREW}]", text):
        return text
    pieces: list[str] = []
    position = 0
    for match in _RTL_RUN_RE.finditer(text):
        start, end = match.span()
        pieces.append(text[position:start])
        pieces.append(_reverse_run(text[start:end]))
        position = end
    pieces.append(text[position:])
    return "".join(pieces)


class _VisualHebrewStream:
    """Wraps stdout / stderr so everything printed goes through visual_hebrew()."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text: str):
        return self._stream.write(visual_hebrew(text))

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def install_console_bidi_fix() -> None:
    """Fix Hebrew on terminals only - output redirected to a file / pipe stays in normal order."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is not None and stream.isatty() and not isinstance(stream, _VisualHebrewStream):
            setattr(sys, name, _VisualHebrewStream(stream))


def use_utf8_output() -> None:
    """Hebrew / ◯ on Windows consoles."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def print_table(headers: list[str], rows: list[list]) -> None:
    """Print a table with padded columns. Numbers are right-aligned, empty values show as '-'."""
    shown = [["-" if value == "" else str(value) for value in row] for row in rows]
    is_numeric = [all(isinstance(row[i], int) or row[i] == "" for row in rows)
                  for i in range(len(headers))]
    widths = [max([len(headers[i])] + [len(row[i]) for row in shown]) for i in range(len(headers))]

    def format_row(cells: list[str]) -> str:
        padded = [cell.rjust(width) if numeric else cell.ljust(width)
                  for cell, width, numeric in zip(cells, widths, is_numeric)]
        return " | ".join(padded).rstrip()

    print(format_row(headers))
    print("-+-".join("-" * width for width in widths))
    for row in shown:
        print(format_row(row))
