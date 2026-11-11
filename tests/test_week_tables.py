import contextlib
import io
import unittest
from datetime import date
from types import SimpleNamespace

from immersion_tracker.planning import SheetCell
from immersion_tracker.settings import AppearanceSettings, CalendarSettings, ConjugationSettings, SheetSettings
from immersion_tracker.sheets.week_tables import (SheetSnapshot, cell_state, circle_total, decide_cell_writes,
                                                  find_week_blocks)
from immersion_tracker.timeline import Calendar

CALENDAR = Calendar(CalendarSettings())
SHEET = SheetSettings()
LABELS = ["日", "月", "火", "水", "木", "金", "土"]


def tab(tables=2, students=("Alice", "Ben")):
    """Values of a tab holding `tables` week tables stacked every 9 rows."""
    values = []
    for _ in range(tables):
        values.append(["曜日", *students])
        values.extend([label] for label in LABELS)
        values.append([])
    return values


def table(name, index, width=3):
    return {"name": name, "range": {"startRowIndex": index * 9, "startColumnIndex": 0, "endColumnIndex": width}}


class FindWeekBlocksTests(unittest.TestCase):
    def find(self, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return find_week_blocks(*args, **kwargs)

    def test_conjugation_tables_are_found_by_their_own_names(self):
        regex = ConjugationSettings().table_name_regex
        tables = [table("הטיות שבוע 3", 0), table("הטיות שבוע 4", 1), table("week 1", 2)]
        blocks = self.find(tab(3), tables, SHEET, CALENDAR, regex)
        self.assertEqual(sorted(blocks), [3, 4])                       # "week 1" is not a conjugation table
        self.assertEqual(blocks[4].header_row, 9)
        self.assertEqual(blocks[3].column_names, ["Alice", "Ben"])

    def test_the_main_tab_ignores_conjugation_tables(self):
        blocks = self.find(tab(2), [table("week 1", 0), table("הטיות שבוע 3", 1)], SHEET, CALENDAR)
        self.assertEqual(sorted(blocks), [1])

    def test_unnamed_tables_are_numbered_from_first_number(self):
        blocks = self.find(tab(3), [], SHEET, CALENDAR, first_number=3)
        self.assertEqual(sorted(blocks), [3, 4, 5])
        self.assertEqual(sorted(self.find(tab(2), [], SHEET, CALENDAR)), [1, 2])      # default numbering unchanged



class CellStateTests(unittest.TestCase):
    APPEARANCE = AppearanceSettings()

    def test_states(self):
        cases = {"": "empty", "  ": "empty", "◯": "circles", "◯◯◯": "circles", "○○": "circles", "✖": "cross", "x": "cross",
                 "a note": "empty"}
        for text, state in cases.items():
            with self.subTest(text=text):
                self.assertEqual(cell_state(text, self.APPEARANCE), state)

    def test_circle_total_treats_look_alike_circles_the_same(self):
        self.assertEqual(circle_total("○○", self.APPEARANCE), circle_total("◯◯", self.APPEARANCE))
        self.assertEqual(circle_total("◯◯◯", self.APPEARANCE), 3)


class DecideCellWritesTests(unittest.TestCase):
    """Empty -> written.  Circles -> kept (a conflict if the chat says another number).  ✖ -> replaced by a late report."""
    SUNDAY = date(2026, 10, 18)             # row 0 of week 1 (weeks start on Sunday); Day 1 is Thursday 22/10
    DAY1 = date(2026, 10, 22)
    APPEARANCE = AppearanceSettings()

    def decide(self, sheet_cells, planned, overwrite=False):
        """sheet_cells / planned: {student: text}; the day is the table's first row."""
        values = tab(1, students=("Alice", "Ben", "Chloe"))
        for student, text in sheet_cells.items():
            values[1] = values[1] + [""] * (4 - len(values[1]))
            values[1][("Alice", "Ben", "Chloe").index(student) + 1] = text
        with contextlib.redirect_stdout(io.StringIO()):
            blocks = find_week_blocks(values, [], SHEET, CALENDAR)
        snapshot = SheetSnapshot(None, SimpleNamespace(id=7), values, blocks)
        plan = {(student, self.SUNDAY): SheetCell(text, green=not text.startswith("✖")) for student, text in planned.items()}
        return decide_cell_writes(plan, self.DAY1, overwrite, snapshot, self.APPEARANCE, CALENDAR)

    def test_an_empty_cell_is_written(self):
        writes = self.decide({}, {"Alice": "◯◯"})
        self.assertEqual(len(writes.requests), 1)
        self.assertEqual((writes.skipped, writes.late_fills, writes.conflicts), (0, [], []))

    def test_a_cross_is_replaced_by_a_late_report(self):
        writes = self.decide({"Alice": "✖"}, {"Alice": "◯◯◯"})
        self.assertEqual(len(writes.requests), 1)
        self.assertEqual(writes.late_fills, [("Alice", self.SUNDAY, "✖", "◯◯◯")])
        self.assertEqual(writes.conflicts, [])

    def test_a_cross_stays_when_there_is_still_nothing_to_report(self):
        writes = self.decide({"Alice": "✖"}, {"Alice": "✖"})
        self.assertEqual((len(writes.requests), writes.skipped, writes.late_fills), (0, 1, []))

    def test_circles_are_kept_and_a_different_chat_is_a_conflict(self):
        writes = self.decide({"Alice": "◯"}, {"Alice": "◯◯◯◯"})
        self.assertEqual(len(writes.requests), 0)
        self.assertEqual(writes.conflicts, [("Alice", self.SUNDAY, "◯", "◯◯◯◯")])

    def test_circles_that_match_the_chat_are_skipped_silently(self):
        writes = self.decide({"Alice": "◯◯", "Ben": "○○"}, {"Alice": "◯◯", "Ben": "◯◯"})
        self.assertEqual((len(writes.requests), writes.skipped, writes.conflicts), (0, 2, []))

    def test_circles_are_not_touched_when_the_chat_has_nothing(self):
        writes = self.decide({"Alice": "◯◯"}, {"Alice": "✖"})              # e.g. filled in by hand
        self.assertEqual((len(writes.requests), writes.skipped, writes.conflicts), (0, 1, []))

    def test_overwrite_replaces_everything(self):
        writes = self.decide({"Alice": "◯", "Ben": "✖", "Chloe": "◯◯"}, {"Alice": "◯◯◯", "Ben": "◯", "Chloe": "✖"}, overwrite=True)
        self.assertEqual(len(writes.requests), 3)
        self.assertEqual((writes.skipped, writes.conflicts), (0, []))


if __name__ == "__main__":
    unittest.main()
