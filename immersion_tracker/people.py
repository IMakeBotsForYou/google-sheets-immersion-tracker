"""Who is a student (and which sheet column is theirs) and who is ignored - stored in people.json."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .textutil import normalize_name


@dataclass
class People:
    path: Path
    students: dict[str, str] = field(default_factory=dict)     # WhatsApp name -> column header in the sheet
    ignored: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "People":
        people = cls(path)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            people.students.update(data.get("students", {}))
            people.ignored.update(data.get("ignore", []))
        return people

    def save(self) -> None:
        data = {"students": self.students, "ignore": sorted(self.ignored)}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def forget(self, normalized_name: str) -> None:
        """Remove a person from both the student list and the ignore list."""
        for name in [n for n in self.students if normalize_name(n) == normalized_name]:
            del self.students[name]
        for name in [n for n in self.ignored if normalize_name(n) == normalized_name]:
            self.ignored.discard(name)

    # --- lookups ------------------------------------------------------------
    def column_by_sender(self) -> dict[str, str]:
        """normalised WhatsApp name -> sheet column."""
        return {normalize_name(name): column for name, column in self.students.items()}

    def ignored_keys(self) -> set[str]:
        return {normalize_name(name) for name in self.ignored}

    def columns(self, sheet_order: Sequence[str] = ()) -> list[str]:
        """Distinct sheet column names of all students, in the order of the sheet's columns (left to right).

        `sheet_order` holds the sheet's normalised headers.  Students whose column isn't in it (or if the sheet
        couldn't be read) keep the setup order, after the rest.
        """
        columns = list(dict.fromkeys(self.students.values()))
        position = {name: index for index, name in enumerate(sheet_order)}
        columns.sort(key=lambda column: position.get(normalize_name(column), len(position)))    # stable sort
        return columns
