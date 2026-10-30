import json
import tempfile
import unittest
from pathlib import Path

from immersion_tracker.people import People
from immersion_tracker.sheets.week_tables import WeekBlock, sheet_order


class PeopleTests(unittest.TestCase):
    def test_round_trip_and_forget(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "people.json"
            people = People(path)
            people.students["Alice Cohen"] = "Alice"
            people.ignored.add("Teacher")
            people.save()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             {"students": {"Alice Cohen": "Alice"}, "ignore": ["Teacher"]})
            loaded = People.load(path)
            self.assertEqual(loaded.students, {"Alice Cohen": "Alice"})
            loaded.forget("alice cohen")
            self.assertEqual(loaded.students, {})

    def test_lookup_ignores_case_and_invisible_marks(self):
        people = People(Path("x"), {"~Alice\u200f Cohen": "Alice"}, {"TEACHER"})
        self.assertEqual(people.column_by_sender(), {"alice cohen": "Alice"})
        self.assertEqual(people.ignored_keys(), {"teacher"})


class ColumnOrderTests(unittest.TestCase):
    def setUp(self):
        self.people = People(Path("x"), {"a": "Gina", "b": "Hugo", "c": "Iris", "d": "Sam"})

    def test_without_a_sheet_the_setup_order_is_kept(self):
        self.assertEqual(self.people.columns(), ["Gina", "Hugo", "Iris", "Sam"])

    def test_the_sheet_order_wins(self):
        self.assertEqual(self.people.columns(["sam", "gina", "iris", "hugo"]), ["Sam", "Gina", "Iris", "Hugo"])

    def test_students_missing_from_the_sheet_go_last_in_setup_order(self):
        self.assertEqual(self.people.columns(["sam", "iris"]), ["Sam", "Iris", "Gina", "Hugo"])

    def test_two_names_for_one_column_appear_once(self):
        people = People(Path("x"), {"a": "Gina", "a2": "Gina", "b": "Hugo"})
        self.assertEqual(people.columns(), ["Gina", "Hugo"])


class SheetOrderTests(unittest.TestCase):
    def test_first_table_wins_and_new_headers_are_appended(self):
        blocks = {2: WeekBlock(0, {}, ["Hugo", "Gina", "Newcomer"]),
                  1: WeekBlock(0, {}, ["Gina", "Hugo"])}
        self.assertEqual(sheet_order(blocks), ["gina", "hugo", "newcomer"])


if __name__ == "__main__":
    unittest.main()
