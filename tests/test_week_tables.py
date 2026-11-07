import contextlib
import io
import unittest

from immersion_tracker.settings import CalendarSettings, ConjugationSettings, SheetSettings
from immersion_tracker.sheets.week_tables import find_week_blocks
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


if __name__ == "__main__":
    unittest.main()
