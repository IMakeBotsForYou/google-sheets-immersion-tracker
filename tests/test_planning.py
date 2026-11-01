import unittest
from datetime import date, datetime
from pathlib import Path

from immersion_tracker.people import People
from immersion_tracker.planning import collect_day_totals, gather_reports
from immersion_tracker.reports import ReportParser
from immersion_tracker.settings import DEFAULT_ACTIVITIES, DEFAULT_ANKI_WORDS, CalendarSettings
from immersion_tracker.timeline import Calendar
from immersion_tracker.whatsapp import Message

PHONE = "+972 54-676-7474"
CALENDAR = Calendar(CalendarSettings())
PARSER = ReportParser(DEFAULT_ACTIVITIES, DEFAULT_ANKI_WORDS)
PEOPLE = People(Path("x"), {PHONE: "Noam", "Maxim Kondrativ": "Maxim"})
FULL = "צפייה 10\nקריאה 10\nשמיעה 10"


class WarningNamesTests(unittest.TestCase):
    def run_pipeline(self, messages, first_day=date(2026, 10, 25)):
        warnings = []
        warn = lambda text, about_date=None: warnings.append(text)
        found = gather_reports(messages, PEOPLE, PARSER, CALENDAR, warn)
        collect_day_totals(found, date(2026, 10, 22), first_day, date(2026, 10, 30), CALENDAR, "last", warn)
        return warnings

    def assert_names_the_student(self, warnings, expected_count):
        self.assertEqual(len(warnings), expected_count, warnings)
        for text in warnings:
            self.assertIn("Noam", text)
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
        warnings = self.run_pipeline([Message(datetime(2026, 10, 27, 16, 7), "Maxim Kondrativ", "סיכום יום 4\n" + FULL)])
        self.assertIn(" Maxim: ", warnings[0])
        self.assertNotIn("Kondrativ", warnings[0])

    def test_a_sender_who_is_not_saved_yet_is_shown_as_is(self):
        warnings = self.run_pipeline([Message(datetime(2026, 10, 27, 20, 0), "+972 50-000-0000", FULL)])
        self.assertEqual(len(warnings), 1)
        self.assertIn("+972 50-000-0000", warnings[0])
        self.assertIn("--setup", warnings[0])


if __name__ == "__main__":
    unittest.main()
