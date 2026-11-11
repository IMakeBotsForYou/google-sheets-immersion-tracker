import unittest
from datetime import date

from immersion_tracker.reports import DayTotals
from immersion_tracker.sheets.log import (ANKI_COLUMN, CONJUGATIONS_COLUMN, TOTAL_COLUMN, build_log_rows, log_columns,
                                          map_existing_columns)

ACTIVITIES = ["צפייה", "קריאה", "שמיעה", "רילז"]
HEADER = log_columns(ACTIVITIES)
LEGACY = [name for name in HEADER if name != "הטיות"]              # the layout before the conjugations column


class LogColumnsTests(unittest.TestCase):
    def test_the_conjugations_column_sits_between_anki_and_the_total(self):
        self.assertEqual(HEADER[-3:], ["אנקי", "הטיות", "סך הכל (דקות)"])
        self.assertEqual((HEADER[ANKI_COLUMN], HEADER[CONJUGATIONS_COLUMN], HEADER[TOTAL_COLUMN]),
                         ("אנקי", "הטיות", "סך הכל (דקות)"))

    def test_a_row_has_the_count_and_the_total_does_not_include_it(self):
        totals = {("Alice", date(2026, 10, 25)): DayTotals({"צפייה": 60, "קריאה": 30}, 40, 90, 40)}
        (row,) = build_log_rows(totals, date(2026, 10, 22), ["Alice"], ACTIVITIES)
        self.assertEqual(row, ["2026-10-25", 4, "Alice", 60, 30, "", "", 40, 40, 90])
        self.assertEqual(len(row), len(HEADER))
        self.assertEqual(row[TOTAL_COLUMN], 90)                      # 60 + 30: neither Anki nor conjugations is time

    def test_no_conjugations_line_leaves_the_cell_empty(self):
        totals = {("Alice", date(2026, 10, 25)): DayTotals({"צפייה": 60}, None, 60)}
        (row,) = build_log_rows(totals, date(2026, 10, 22), ["Alice"], ACTIVITIES)
        self.assertEqual((row[ANKI_COLUMN], row[CONJUGATIONS_COLUMN]), ("", ""))


class MapExistingColumnsTests(unittest.TestCase):
    def test_the_current_layout(self):
        self.assertEqual(map_existing_columns(HEADER, HEADER), list(range(10)))

    def test_the_layout_before_the_column_existed(self):
        mapping = map_existing_columns(LEGACY, HEADER)
        self.assertEqual(mapping, [0, 1, 2, 3, 4, 5, 6, 7, None, 8])      # the new column has no source in the sheet

    def test_an_empty_header_cell_where_the_column_goes(self):
        """A column added by hand, waiting to be filled: ... אנקי | (empty) | סך הכל (דקות)"""
        placeholder = LEGACY[:-1] + [""] + LEGACY[-1:]
        self.assertEqual(map_existing_columns(placeholder, HEADER), list(range(10)))

    def test_the_old_name_of_a_column_is_still_recognised(self):
        old_names = ["יוטיוב" if name == "צפייה" else name for name in LEGACY]
        self.assertIsNotNone(map_existing_columns(old_names, HEADER))

    def test_something_that_is_not_our_log_is_refused(self):
        self.assertIsNone(map_existing_columns(["name", "score"], HEADER))
        self.assertIsNone(map_existing_columns(LEGACY[:-1] + ["something else"], HEADER))


if __name__ == "__main__":
    unittest.main()
