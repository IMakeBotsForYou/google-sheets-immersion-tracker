import contextlib
import io
import unittest
from datetime import date, datetime
from pathlib import Path

from immersion_tracker.people import People
from immersion_tracker.planning import build_conjugation_plan, collect_day_totals, gather_reports
from immersion_tracker.reports import DayTotals, ReportParser
from immersion_tracker.settings import (DEFAULT_ACTIVITIES, DEFAULT_ANKI_WORDS, AppearanceSettings, CalendarSettings,
                                         ConjugationSettings)
from immersion_tracker.timeline import Calendar
from immersion_tracker.whatsapp import Message

PHONE = "+1 555-010-0199"
CALENDAR = Calendar(CalendarSettings())
PARSER = ReportParser(DEFAULT_ACTIVITIES, DEFAULT_ANKI_WORDS)
PEOPLE = People(Path("x"), {PHONE: "Nora", "Max Example": "Max"})
FULL = "צפייה 10\nקריאה 10\nשמיעה 10"


class WarningNamesTests(unittest.TestCase):
    def run_pipeline(self, messages, first_day=date(2026, 10, 25)):
        warnings = []
        warn = lambda text, about_date=None: warnings.append(text)
        with contextlib.redirect_stdout(io.StringIO()):
            found = gather_reports(messages, PEOPLE, PARSER, CALENDAR, warn)
        collect_day_totals(found, date(2026, 10, 22), first_day, date(2026, 10, 30), CALENDAR, "last", warn)
        return warnings

    def assert_names_the_student(self, warnings, expected_count):
        self.assertEqual(len(warnings), expected_count, warnings)
        for text in warnings:
            self.assertIn("Nora", text)
            self.assertNotIn(PHONE, text)

    def test_unreadable_report_names_the_student_not_the_number(self):
        warnings = self.run_pipeline([Message(datetime(2026, 10, 27, 22, 13), PHONE, "סיכום יום 6:")])
        self.assert_names_the_student(warnings, 1)
        self.assertIn("no activity lines", warnings[0])

    def test_day_number_mismatch_names_the_student(self):
        warnings = self.run_pipeline([Message(datetime(2026, 10, 27, 16, 7), PHONE, "סיכום יום 4\n" + FULL)])
        self.assert_names_the_student(warnings, 1)
        self.assertIn("says Day #4", warnings[0])

    def test_missing_day_number_names_the_student(self):
        warnings = self.run_pipeline([Message(datetime(2026, 10, 30, 8, 58), PHONE, FULL)])
        self.assert_names_the_student(warnings, 1)
        self.assertIn("no day number", warnings[0])

    def test_a_whatsapp_name_is_replaced_by_the_sheet_name_too(self):
        warnings = self.run_pipeline([Message(datetime(2026, 10, 27, 16, 7), "Max Example", "סיכום יום 4\n" + FULL)])
        self.assertIn(" Max: ", warnings[0])
        self.assertNotIn("Example", warnings[0])

    def test_ignored_line_warning_names_the_student(self):
        text = "סיכום יום 6\n" + FULL + "\nהיום לא אספיק שעה אבל אשלים אנקי"
        warnings = self.run_pipeline([Message(datetime(2026, 10, 27, 20, 0), PHONE, text)])
        self.assertEqual(len(warnings), 1)
        self.assertIn("Nora", warnings[0])
        self.assertIn("ignored a line", warnings[0])

    def test_a_sender_who_is_not_saved_yet_is_shown_as_is(self):
        warnings = self.run_pipeline([Message(datetime(2026, 10, 27, 20, 0), "+1 555-010-0100", FULL)])
        self.assertEqual(len(warnings), 1)
        self.assertIn("+1 555-010-0100", warnings[0])
        self.assertIn("--setup", warnings[0])



class ConjugationPlanTests(unittest.TestCase):
    """The conjugations tab: 20 = one circle, 40 = two, less than 20 = a cross."""
    SETTINGS = ConjugationSettings()
    APPEARANCE = AppearanceSettings()
    TODAY = date(2026, 11, 4)

    def plan(self, counts, **overrides):
        """counts: {(student, day-of-november): conjugations}"""
        totals = {(student, date(2026, 11, day)): DayTotals({}, None, 0, count) for (student, day), count in counts.items()}
        settings = ConjugationSettings(**overrides) if overrides else self.SETTINGS
        return build_conjugation_plan(totals, ["A", "B"], date(2026, 11, 1), self.TODAY, settings, self.APPEARANCE)

    def test_circles_per_twenty_and_a_cross_below(self):
        plan = self.plan({("A", 1): 20, ("A", 2): 40, ("A", 3): 19, ("B", 1): 0, ("B", 2): 59, ("B", 3): 100})
        self.assertEqual({key[1].day: cell.text for key, cell in plan.items() if key[0] == "A"}, {1: "◯", 2: "◯◯", 3: "✖"})
        self.assertEqual({key[1].day: cell.text for key, cell in plan.items() if key[0] == "B"}, {1: "✖", 2: "◯◯", 3: "◯◯◯◯◯"})

    def test_colours(self):
        plan = self.plan({("A", 1): 40, ("A", 2): 5})
        self.assertTrue(plan[("A", date(2026, 11, 1))].green)
        self.assertFalse(plan[("A", date(2026, 11, 2))].green)

    def test_a_finished_day_without_the_line_or_without_a_report_is_a_cross(self):
        plan = self.plan({("A", 1): 40})
        self.assertEqual(plan[("B", date(2026, 11, 1))].text, "✖")       # B reported nothing
        self.assertEqual(plan[("A", date(2026, 11, 2))].text, "✖")

    def test_the_day_in_progress_is_not_crossed_yet(self):
        plan = self.plan({("A", 4): 10})                                 # today (Nov 4) with a small count so far
        self.assertNotIn(("A", self.TODAY), plan)
        self.assertNotIn(("B", self.TODAY), plan)
        plan = self.plan({("A", 4): 20})                                 # ...but circles are shown as soon as they are earned
        self.assertEqual(plan[("A", self.TODAY)].text, "◯")

    def test_per_circle_is_configurable(self):
        plan = self.plan({("A", 1): 30}, per_circle=10)
        self.assertEqual(plan[("A", date(2026, 11, 1))].text, "◯◯◯")


if __name__ == "__main__":
    unittest.main()
