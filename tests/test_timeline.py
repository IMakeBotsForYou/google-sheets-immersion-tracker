import unittest
from datetime import date, datetime, time

from immersion_tracker.errors import ConfigError
from immersion_tracker.settings import CalendarSettings
from immersion_tracker.timeline import Calendar


def calendar(**overrides):
    base = dict(day_1_date=date(2026, 10, 22), timezone="Asia/Jerusalem", chat_timezone="Asia/Tokyo")
    return Calendar(CalendarSettings(**{**base, **overrides}))


class ImmersionDayTests(unittest.TestCase):
    def test_a_day_ends_at_the_cutoff_not_at_midnight(self):
        cal = calendar()
        self.assertEqual(cal.immersion_day(datetime(2026, 10, 31, 2, 0)), date(2026, 10, 30))
        self.assertEqual(cal.immersion_day(datetime(2026, 10, 31, 5, 0)), date(2026, 10, 31))

    def test_custom_cutoff(self):
        cal = calendar(day_ends_at=time(3, 0))
        self.assertEqual(cal.immersion_day(datetime(2026, 10, 31, 2, 59)), date(2026, 10, 30))
        self.assertEqual(cal.immersion_day(datetime(2026, 10, 31, 3, 0)), date(2026, 10, 31))


class TimeZoneTests(unittest.TestCase):
    def test_tokyo_to_israel_follows_daylight_saving(self):
        cal = calendar()
        self.assertEqual(cal.chat_to_local(datetime(2026, 10, 30, 8, 58)), datetime(2026, 10, 30, 1, 58))   # winter: -7 h
        self.assertEqual(cal.chat_to_local(datetime(2026, 7, 1, 12, 0)), datetime(2026, 7, 1, 6, 0))        # summer: -6 h

    def test_no_chat_timezone_means_same_zone(self):
        cal = Calendar(CalendarSettings())
        self.assertEqual(cal.chat_to_local(datetime(2026, 10, 30, 8, 58)), datetime(2026, 10, 30, 8, 58))

    def test_format_start_is_converted(self):
        cal = calendar(format_start=datetime(2026, 10, 26, 9, 57))
        self.assertEqual(cal.format_start_local, datetime(2026, 10, 26, 2, 57))


class WeekTableTests(unittest.TestCase):
    def test_rows_and_week_one_start(self):
        cal = calendar()                                            # weeks start Sunday, Day 1 = Thursday 22/10
        self.assertEqual(cal.row_in_week_table(date(2026, 10, 22)), 4)
        self.assertEqual(cal.week1_first_row_date(date(2026, 10, 22)), date(2026, 10, 18))

    def test_skip_days(self):
        cal = calendar()
        day1 = date(2026, 10, 22)
        self.assertEqual(cal.skip_days(day1), 0)                    # skip_until_week = 1 (default)
        self.assertEqual(calendar(skip_until_week=2).skip_days(day1), 3)
        self.assertEqual(calendar(skip_until_week=2, skip_first_days=1).skip_days(day1), 1)
        self.assertEqual(calendar(skip_until_week=2).skip_days(day1, cli_skip_first=5), 5)
        self.assertEqual(calendar().skip_days(day1, cli_skip_until_week=3), 10)

    def test_expected_labels_rotate_with_week_start(self):
        labels = ("月", "火", "水", "木", "金", "土", "日")
        self.assertEqual("".join(calendar().expected_weekday_labels(labels)), "日月火水木金土")
        self.assertEqual("".join(calendar(week_starts_on="monday").expected_weekday_labels(labels)), "月火水木金土日")


class ValidationTests(unittest.TestCase):
    def test_bad_weekday(self):
        with self.assertRaises(ConfigError):
            calendar(week_starts_on="someday")


if __name__ == "__main__":
    unittest.main()
