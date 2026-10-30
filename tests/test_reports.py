import unittest
from datetime import datetime

from immersion_tracker.reports import Report, ReportParser, circle_count, merge_reports
from immersion_tracker.settings import DEFAULT_ACTIVITIES, DEFAULT_ANKI_WORDS
from immersion_tracker.whatsapp import Message

PARSER = ReportParser(DEFAULT_ACTIVITIES, DEFAULT_ANKI_WORDS)
SENT = datetime(2026, 10, 28, 21, 0)


def extract(text):
    return PARSER.extract(Message(SENT, "Alice", text))


class ExtractReportTests(unittest.TestCase):
    def test_full_report(self):
        report, problem = extract("סיכום יום 7\nצפייה 1 שעה ו-20 דקות\nקריאה 30\nשמיעה חצי שעה\nרילז 10 דקות\nאנקי 20 קלפים")
        self.assertIsNone(problem)
        self.assertEqual(report.day_number, 7)
        self.assertEqual(report.minutes_by_activity, {"צפייה": 80, "קריאה": 30, "שמיעה": 30, "רילז": 10})
        self.assertEqual(report.total_minutes, 150)
        self.assertEqual(report.anki_cards, 20)

    def test_aliases_are_added_up(self):
        report, _ = extract("יום 3\nצפייה 10\nיוטיוב 20\nשמיעה 5\nשמיעה פסיבית 15")
        self.assertEqual(report.minutes_by_activity["צפייה"], 30)
        self.assertEqual(report.minutes_by_activity["שמיעה"], 20)

    def test_whatsapp_formatting_marks_are_ignored(self):
        report, _ = extract("*סיכום יום 7*\n*צפייה* 10\n_קריאה_ 10\n~שמיעה~ 10")
        self.assertEqual(report.total_minutes, 30)

    def test_ordinary_chat_is_not_a_report(self):
        self.assertEqual(extract("מישהו מכיר ערוץ יוטיוב טוב?"), (None, None))

    def test_unreadable_duration_is_a_problem(self):
        report, problem = extract("סיכום יום 7\nצפייה כמה שיכולתי\nקריאה 20\nשמיעה 30")
        self.assertIsNone(report)
        self.assertIn("צפייה", problem)

    def test_unreadable_anki_keeps_the_report(self):
        report, _ = extract("סיכום יום 7\nצפייה 10\nקריאה 20\nשמיעה 30\nאנקי הרבה")
        self.assertIsNotNone(report)
        self.assertIsNone(report.anki_cards)
        self.assertTrue(report.notes)

    def test_two_lines_without_header_is_flagged(self):
        report, problem = extract("צפייה 10\nקריאה 20")
        self.assertIsNone(report)
        self.assertIn("סיכום יום", problem)


class CircleCountTests(unittest.TestCase):
    def test_rounding_modes(self):
        self.assertEqual([circle_count(95, m) for m in ("floor", "round", "ceil")], [1, 2, 2])

    def test_any_immersion_gives_a_circle_and_none_gives_zero(self):
        self.assertEqual(circle_count(10), 1)
        self.assertEqual(circle_count(0), 0)


class MergeReportsTests(unittest.TestCase):
    def setUp(self):
        self.reports = [Report(SENT, 7, {"צפייה": 30}, 10), Report(SENT, 7, {"צפייה": 90}, None)]

    def test_modes(self):
        self.assertEqual(merge_reports(self.reports, "last").total_minutes, 90)
        self.assertEqual(merge_reports(self.reports, "sum").total_minutes, 120)
        self.assertEqual(merge_reports(self.reports, "max").total_minutes, 90)
        self.assertEqual(merge_reports(self.reports, "sum").anki_cards, 10)


if __name__ == "__main__":
    unittest.main()
