import unittest
from datetime import datetime

from immersion_tracker.reports import Report, ReportParser, circle_count, merge_reports
from immersion_tracker.settings import DEFAULT_ACTIVITIES, DEFAULT_ANKI_WORDS
from immersion_tracker.whatsapp import Message

PARSER = ReportParser(DEFAULT_ACTIVITIES, DEFAULT_ANKI_WORDS, ("הטיות", "הטיה"))
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


class NumberFirstLineTests(unittest.TestCase):
    """The amount may come first and the keyword last ("60 דקות קריאה"); both forms can be mixed in one report."""

    def parts(self, text):
        report, problem = extract(text)
        self.assertIsNone(problem, text)
        return report

    def test_the_first_example(self):
        report = self.parse_example("סיכום יום 6:\n60 דקות קריאה \n15 דקות פודקאסט\n40 דקות צפייה")
        self.assertEqual(report.day_number, 6)
        self.assertEqual(report.minutes_by_activity, {"קריאה": 60, "שמיעה": 15, "צפייה": 40})   # a podcast is listening
        self.assertEqual((report.total_minutes, report.notes), (115, []))

    def test_the_second_example_needs_no_day_line(self):
        report = self.parse_example("30 דקות קריאה \n30 דקות פודקאסט \nאנקי 15 קלפים")
        self.assertIsNone(report.day_number)
        self.assertEqual(report.minutes_by_activity, {"קריאה": 30, "שמיעה": 30})
        self.assertEqual((report.anki_cards, report.notes), (15, []))

    def test_mixed_forms_in_one_report(self):
        report = self.parse_example("סיכום יום 7\nקריאה 20 דקות\n30 דקות פודקאסט\nצפייה שעה וחצי\n15 קלפים אנקי\n40 הטיות")
        self.assertEqual(report.minutes_by_activity, {"קריאה": 20, "שמיעה": 30, "צפייה": 90})
        self.assertEqual((report.anki_cards, report.conjugations, report.notes), (15, 40, []))

    def parse_example(self, text):
        report, problem = extract(text)
        self.assertIsNone(problem, text)
        self.assertIsNotNone(report, text)
        return report

    def test_amount_styles_in_front_of_the_keyword(self):
        cases = {"60 דקות קריאה": 60, "60 קריאה": 60, "שעה וחצי קריאה": 90, "1 שעה ו-20 דקות קריאה": 80,
                 "1:30 קריאה": 90, "רבע שעה קריאה": 15, "20 דקות של קריאה": 20, "45 דקות קריאה.": 45, "0 קריאה": 0}
        for line, minutes in cases.items():
            with self.subTest(line=line):
                report = self.parse_example(f"סיכום יום 6\n{line}")
                self.assertEqual(report.minutes_by_activity, {"קריאה": minutes})

    def test_every_listening_word_in_either_order(self):
        for word in ("שמיעה", "שמיעה פסיבית", "הקשבה", "פודקאסט", "פודקסט", "פודקאסטים"):
            for line in (f"{word} 25 דקות", f"25 דקות {word}"):
                with self.subTest(line=line):
                    self.assertEqual(self.parse_example(f"סיכום יום 6\n{line}").minutes_by_activity, {"שמיעה": 25})

    def test_different_names_of_one_activity_are_added_up_whatever_the_form(self):
        report = self.parse_example("סיכום יום 6\nשמיעה 10 דקות\n20 דקות פודקאסט\n30 דקות שמיעה פסיבית")
        self.assertEqual(report.minutes_by_activity, {"שמיעה": 60})

    def test_anki_and_conjugations_amount_first(self):
        base = "סיכום יום 6\nקריאה 10\n"
        for line, cards in {"15 קלפים אנקי": 15, "15 אנקי": 15, "400+ קלפים אנקי": 400, "0 אנקי": 0}.items():
            with self.subTest(line=line):
                self.assertEqual(self.parse_example(base + line).anki_cards, cards)
        for line, count in {"40 הטיות": 40, "40 תרגילים הטיות": 40, "20 הטיה": 20}.items():
            with self.subTest(line=line):
                self.assertEqual(self.parse_example(base + line).conjugations, count)

    def test_a_sentence_is_not_mistaken_for_a_line(self):
        """The text before the keyword must be an amount and nothing else."""
        base = "סיכום יום 6\nצפייה 10\nשמיעה 10\nרילז 10\n"
        for sentence in ("היום עשיתי 20 דקות קריאה", "אולי 20 דקות קריאה", "ביום 6 קריאה", "הרבה קריאה"):
            with self.subTest(sentence=sentence):
                report = self.parse_example(base + sentence)
                self.assertNotIn("קריאה", report.minutes_by_activity)      # not counted ...
                self.assertTrue(any(sentence in note for note in report.notes))    # ... but warned about

    def test_a_number_first_line_is_not_an_ignored_line(self):
        self.assertEqual(self.parse_example("סיכום יום 6\n60 דקות קריאה\n15 דקות פודקאסט").notes, [])

    def test_ordinary_chat_with_an_activity_word_is_still_chat(self):
        self.assertEqual(extract("מישהו מכיר ערוץ יוטיוב טוב?"), (None, None))
        self.assertEqual(extract("אני סיימתי 20 דקות קריאה"), (None, None))


class ConjugationLineTests(unittest.TestCase):
    BASE = "יום 9\nצפייה 100 דקות\nשמיעה 100 דקות\nאנקי 100 קלפים\n"

    def test_the_example_from_the_spec(self):
        report, problem = extract(self.BASE + "הטיות 40")
        self.assertIsNone(problem)
        self.assertEqual(report.conjugations, 40)
        self.assertEqual(report.total_minutes, 200)          # conjugations are not minutes
        self.assertEqual(report.anki_cards, 100)
        self.assertEqual(report.notes, [])

    def test_no_unit_needed_and_other_spellings(self):
        for line, count in {"הטיות 40": 40, "הטיות: 40": 40, "הטיה 20": 20, "הטיות 40 תרגילים": 40,
                            "הטיות - 0": 0, "הטיות אין": 0, "*הטיות* 60": 60}.items():
            with self.subTest(line=line):
                self.assertEqual(extract(self.BASE + line)[0].conjugations, count)

    def test_no_line_means_none(self):
        self.assertIsNone(extract(self.BASE)[0].conjugations)

    def test_an_unreadable_count_keeps_the_report(self):
        report, _ = extract(self.BASE + "הטיות הרבה")
        self.assertIsNone(report.conjugations)
        self.assertTrue(any("conjugations" in note for note in report.notes))

    def test_the_line_alone_with_a_day_number_is_a_report(self):
        report, _ = extract("יום 9\nהטיות 40")
        self.assertEqual((report.conjugations, report.total_minutes), (40, 0))

    def test_when_the_feature_is_off_the_line_is_just_an_ignored_line(self):
        plain = ReportParser(DEFAULT_ACTIVITIES, DEFAULT_ANKI_WORDS)
        report, _ = plain.extract(Message(SENT, "Alice", self.BASE + "הטיות 40"))
        self.assertIsNone(report.conjugations)
        self.assertTrue(any("הטיות 40" in note for note in report.notes))


class IgnoredLineTests(unittest.TestCase):
    """Free text inside a report is ignored, but a warning says so when it might have carried data."""
    BASE = "סיכום יום 9:\nקריאה 20 דקות\nשמיעה 20 דקות\nצפייה 5 דקות\nאנקי 40 קלפים\n"

    def notes(self, extra):
        report, problem = extract(self.BASE + extra)
        self.assertIsNone(problem)
        return report, report.notes

    def test_the_comment_from_the_bug_report_is_ignored_but_warned_about(self):
        report, notes = self.notes("\nהיום כנראה גם לא אספיק שעה אבל כן אשלים אנקי ואקרא כי זה כיף")
        self.assertEqual((report.total_minutes, report.anki_cards), (45, 40))      # the numbers are unaffected
        self.assertEqual(len(notes), 1)
        self.assertIn("היום כנראה", notes[0])
        self.assertIn("not counted", notes[0])

    def test_a_typo_in_an_activity_name_is_caught(self):
        _, notes = self.notes("קריאת 20 דקות")
        self.assertEqual(len(notes), 1)

    def test_harmless_lines_get_no_warning(self):
        for extra in ["", "\n", "תודה לכולם!", "🔥🔥", "   "]:
            with self.subTest(extra=extra):
                self.assertEqual(self.notes(extra)[1], [])

    def test_a_clean_report_has_no_notes(self):
        self.assertEqual(extract(self.BASE)[0].notes, [])

    def test_an_absurd_day_number_is_ignored_with_a_note(self):
        report, _ = extract("יום 29013890321890231890231\nצפייה 100 דקות\nשמיעה 100 דקות\nהטיות 40")
        self.assertIsNone(report.day_number)
        self.assertTrue(any("not a real day number" in note for note in report.notes))


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

    def test_a_follow_up_with_only_conjugations_or_anki_never_replaces_the_full_report(self):
        full = Report(SENT, 7, {"צפייה": 90}, None)
        follow_up = Report(SENT, 7, {}, 30, [], 40)                  # "יום 7 / אנקי 30 / הטיות 40", sent later
        for mode in ("last", "max"):
            with self.subTest(mode=mode):
                merged = merge_reports([full, follow_up], mode)
                self.assertEqual((merged.total_minutes, merged.anki_cards, merged.conjugations), (90, 30, 40))
        self.assertEqual(merge_reports([follow_up, full], "last").total_minutes, 90)    # in either order

    def test_the_full_reports_own_values_win_over_a_follow_up(self):
        full = Report(SENT, 7, {"צפייה": 90}, 10, [], 20)
        follow_up = Report(SENT, 7, {}, 30, [], 40)
        merged = merge_reports([full, follow_up], "last")
        self.assertEqual((merged.anki_cards, merged.conjugations), (10, 20))

    def test_a_day_with_only_follow_ups_is_still_a_report(self):
        merged = merge_reports([Report(SENT, 7, {}, None, [], 40)], "last")
        self.assertEqual((merged.total_minutes, merged.conjugations), (0, 40))

    def test_conjugations_follow_the_same_modes(self):
        reports = [Report(SENT, 7, {"צפייה": 30}, None, [], 20), Report(SENT, 7, {"צפייה": 90}, None, [], 40)]
        self.assertEqual(merge_reports(reports, "last").conjugations, 40)
        self.assertEqual(merge_reports(reports, "sum").conjugations, 60)
        self.assertIsNone(merge_reports(self.reports, "sum").conjugations)


if __name__ == "__main__":
    unittest.main()
