import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from immersion_tracker.errors import ConfigError
from immersion_tracker.settings import Settings, load_settings, parse_time_of_day, settings_from_table

ROOT = Path(__file__).resolve().parent.parent


class SettingsTests(unittest.TestCase):
    def test_defaults_work_without_a_file(self):
        settings = load_settings(None)
        self.assertEqual(settings, Settings())
        self.assertEqual(settings.reports.rounding, "floor")
        self.assertTrue(settings.charts.enabled)

    def test_example_config_loads_with_the_expected_types(self):
        settings = load_settings(ROOT / "config.example.toml")
        self.assertEqual(settings.calendar.day_1_date, date(2026, 10, 22))
        self.assertEqual(settings.calendar.day_ends_at, time(5, 0))
        self.assertEqual(settings.calendar.format_start, datetime(2026, 10, 26, 9, 57))
        self.assertEqual(settings.calendar.chat_timezone, "Asia/Tokyo")
        self.assertEqual(list(settings.reports.activities), ["צפייה", "קריאה", "שמיעה", "רילז"])
        self.assertEqual(settings.sheet.weekday_labels, ("月", "火", "水", "木", "金", "土", "日"))

    def test_partial_override_keeps_the_other_defaults(self):
        settings = settings_from_table({"charts": {"hours_cumulative": False}})
        self.assertFalse(settings.charts.hours_cumulative)
        self.assertTrue(settings.charts.cards_cumulative)

    def test_typos_are_rejected(self):
        for table in ({"calender": {}}, {"calendar": {"day_ends": "05:00"}}):
            with self.subTest(table=table), self.assertRaises(ConfigError):
                settings_from_table(table)

    def test_bad_values_are_rejected_with_the_key_name(self):
        cases = [{"reports": {"rounding": "nearest"}}, {"appearance": {"green": "green"}},
                 {"calendar": {"day_ends_at": "25:00"}}, {"charts": {"width_px": 0}},
                 {"sheet": {"weekday_labels": ["a", "b"]}}]
        for table in cases:
            with self.subTest(table=table), self.assertRaises(ConfigError):
                settings_from_table(table)

    def test_log_tab_must_differ_from_the_week_tab(self):
        with self.assertRaises(ConfigError):
            settings_from_table({"sheet": {"worksheet": "Tab", "log_worksheet": " tab "}})

    def test_empty_log_worksheet_disables_the_log(self):
        self.assertIsNone(settings_from_table({"sheet": {"log_worksheet": ""}}).sheet.log_worksheet)

    def test_missing_and_broken_files(self):
        with self.assertRaises(ConfigError):
            load_settings(ROOT / "does-not-exist.toml")
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "config.toml"
            broken.write_text("[calendar\nx = ", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_settings(broken)

    def test_time_of_day(self):
        self.assertEqual(parse_time_of_day("5"), time(5, 0))
        self.assertEqual(parse_time_of_day("04:30"), time(4, 30))
        with self.assertRaises(ValueError):
            parse_time_of_day("24:00")


if __name__ == "__main__":
    unittest.main()
