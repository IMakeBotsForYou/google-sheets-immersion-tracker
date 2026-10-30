"""Colour conversion for the Sheets API."""
from __future__ import annotations


def hex_to_rgb(color: str) -> dict:
    """'#34A853' -> {'red': 0.2, 'green': 0.66, 'blue': 0.33} (the 0-1 floats the Sheets API wants)."""
    return {"red": int(color[1:3], 16) / 255, "green": int(color[3:5], 16) / 255, "blue": int(color[5:7], 16) / 255}
