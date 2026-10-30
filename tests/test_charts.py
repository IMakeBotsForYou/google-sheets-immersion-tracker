import itertools
import math
import random
import unittest

from immersion_tracker.settings import ChartSettings
from immersion_tracker.sheets.charts import (all_possible_chart_titles, build_chart_tables, chart_column, chart_grid,
                                             chart_titles, line_chart_request)
from immersion_tracker.sheets.palette import PALETTE, student_colors

NAMES = ["Alice", "Ben", "Chloe", "Dan", "Eve", "Frank", "Grace", "Heidi", "Ivan", "Judy"]


def lab(hex_color):
    """sRGB hex -> CIELAB (to measure how different two colours look)."""
    def linear(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(int(hex_color[i:i + 2], 16) / 255) for i in (1, 3, 5))
    x, y, z = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b, (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


class ColorTests(unittest.TestCase):
    def test_palette_colours_are_clearly_different(self):
        closest = min(math.dist(lab(a), lab(b)) for a, b in itertools.combinations(PALETTE, 2))
        self.assertGreaterEqual(closest, 38)

    def test_every_student_gets_a_different_colour(self):
        self.assertEqual(len(set(student_colors(NAMES).values())), len(NAMES))

    def test_colours_do_not_depend_on_column_order(self):
        base = student_colors(NAMES)
        for seed in range(10):
            shuffled = NAMES[:]
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(student_colors(shuffled), base)

    def test_more_students_than_palette_colours_still_works(self):
        colors = student_colors([f"student {i}" for i in range(20)])
        self.assertEqual(len(colors), 20)
        self.assertTrue(all(c.startswith("#") and len(c) == 7 for c in colors.values()))


def log_row(day, student, minutes, anki):
    return [f"2026-10-{21 + day:02d}", day, student, "", "", "", "", anki, minutes]


class ChartDataTests(unittest.TestCase):
    ROWS = [log_row(4, "A", 60, 10), log_row(4, "B", 30, ""), log_row(6, "A", 120, 5), log_row(7, "A", 600, 99)]

    def test_running_totals_and_gaps(self):
        days, hours, cards = build_chart_tables(self.ROWS, ["A", "B"], today_number=6, settings=ChartSettings())
        self.assertEqual(days, [4, 5, 6])                           # day 7 is in the future: ignored
        self.assertEqual(hours["A"], [1.0, 1.0, 3.0])               # day 5 has no report: counts as 0, total carries on
        self.assertEqual(hours["B"], [0.5, 0.5, 0.5])
        self.assertEqual(cards["A"], [10, 10, 15])
        self.assertEqual(cards["B"], [0, 0, 0])                     # empty Anki cell counts as 0

    def test_per_day_mode(self):
        settings = ChartSettings(hours_cumulative=False, cards_cumulative=False)
        days, hours, cards = build_chart_tables(self.ROWS, ["A"], 6, settings)
        self.assertEqual(hours["A"], [1.0, 0.0, 2.0])
        self.assertEqual(cards["A"], [10, 0, 5])

    def test_finished_days_without_reports_extend_the_range(self):
        days, *_ = build_chart_tables(self.ROWS, ["A"], today_number=10, settings=ChartSettings())
        self.assertEqual(days, [4, 5, 6, 7, 8, 9])                  # up to yesterday (day 9); today (10) is still in progress

    def test_nothing_logged_yet(self):
        self.assertIsNone(build_chart_tables([], ["A"], 5, ChartSettings()))

    def test_grid_layout(self):
        days, hours, cards = build_chart_tables(self.ROWS, ["A", "B"], 6, ChartSettings())
        grid = chart_grid(days, ["A", "B"], hours, cards)
        self.assertEqual(grid[0], ["יום", "A", "B", "", "יום", "A", "B"])
        self.assertEqual(grid[1], [4, 1.0, 0.5, "", 4, 10, 0])


class ChartRequestTests(unittest.TestCase):
    def test_the_two_charts_line_up(self):
        settings = ChartSettings()
        columns = ["A", "B"]
        colors = student_colors(columns)
        common = dict(data_sheet_id=7, row_count=4, columns=columns, colors=colors, anchor_sheet_id=3,
                      anchor_column=chart_column(settings, 9), settings=settings)
        top = line_chart_request(title="t", y_title="y", first_col=0, anchor_row=0, **common)
        bottom = line_chart_request(title="t", y_title="y", first_col=len(columns) + 2, anchor_row=17, **common)
        top_pos, bottom_pos = (r["addChart"]["chart"]["position"]["overlayPosition"] for r in (top, bottom))
        self.assertEqual(top_pos["anchorCell"]["columnIndex"], bottom_pos["anchorCell"]["columnIndex"])
        self.assertEqual((top_pos["offsetXPixels"], top_pos["widthPixels"]), (bottom_pos["offsetXPixels"], bottom_pos["widthPixels"]))
        self.assertGreaterEqual(bottom_pos["anchorCell"]["rowIndex"] * 21, top_pos["heightPixels"])    # no overlap

    def test_one_series_per_student_with_its_own_colour(self):
        settings = ChartSettings()
        colors = student_colors(["A", "B"])
        request = line_chart_request(title="t", y_title="y", data_sheet_id=7, first_col=0, row_count=4,
                                     columns=["A", "B"], colors=colors, anchor_sheet_id=3, anchor_row=0,
                                     anchor_column=10, settings=settings)
        series = request["addChart"]["chart"]["spec"]["basicChart"]["series"]
        self.assertEqual([s["series"]["sourceRange"]["sources"][0]["startColumnIndex"] for s in series], [1, 2])
        self.assertNotEqual(series[0]["colorStyle"], series[1]["colorStyle"])

    def test_titles_and_default_column(self):
        self.assertIn(chart_titles(ChartSettings())["hours"], all_possible_chart_titles())
        self.assertIn(chart_titles(ChartSettings(hours_cumulative=False))["hours"], all_possible_chart_titles())
        self.assertEqual(chart_column(ChartSettings(), 9), 10)
        self.assertEqual(chart_column(ChartSettings(column=3), 9), 3)


if __name__ == "__main__":
    unittest.main()
