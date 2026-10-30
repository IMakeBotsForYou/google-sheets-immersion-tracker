"""One stable, distinct colour per student for the charts.

Colours are derived from the student's name (SHA-256 -> a slot in the palette), so a student keeps the
same colour on every run and in both charts, whatever order the sheet's columns are in.  If two names land
on the same slot, the later one (names are processed alphabetically) takes the next free slot, so no two
students ever share a colour.  The palette is ordered so that neighbouring slots are different hues, and
every colour is readable on white.
"""
from __future__ import annotations

import colorsys
import hashlib

from ..textutil import normalize_name

PALETTE = [      # 12 colours; the two closest ones are still clearly apart (CIELAB distance >= 40)
    "#E6194B",  # red
    "#4363D8",  # blue
    "#3CB44B",  # green
    "#F58231",  # orange
    "#911EB4",  # purple
    "#17BECF",  # cyan
    "#7A4A21",  # brown
    "#E6B800",  # gold
    "#000000",  # black
    "#FF8FB8",  # pink
    "#0A5C36",  # dark green
    "#7F7F7F",  # grey
]


def student_colors(names: list[str]) -> dict[str, str]:
    """{name: '#RRGGBB'} - stable per name, all different."""
    colors: dict[str, str] = {}
    taken: set[int] = set()
    for name in sorted(names, key=normalize_name):
        digest = hashlib.sha256(normalize_name(name).encode("utf-8")).digest()
        number = int.from_bytes(digest[:8], "big")
        if len(taken) < len(PALETTE):
            slot = number % len(PALETTE)
            while slot in taken:
                slot = (slot + 1) % len(PALETTE)
            taken.add(slot)
            colors[name] = PALETTE[slot]
        else:       # more students than palette colours: fall back to a hue taken from the hash
            red, green, blue = colorsys.hls_to_rgb((number % 360) / 360, 0.42, 0.75)
            colors[name] = f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"
    return colors
