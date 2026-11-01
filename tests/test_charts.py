import itertools
import math
import random
import unittest

from immersion_tracker.settings import ChartSettings
from immersion_tracker.sheets.charts import (all_possible_chart_titles, build_chart_tables, chart_column, chart_grid,
                                             chart_titles, line_chart_request, merge_chart_data, mode_marker,
                                             read_stored_data)
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



def as_sheet_text(grid):
    """What get_all_values() gives back: everything as text, trailing blanks trimmed."""
    return [[str(cell) for cell in row] for row in grid]


class AddOnlyMergeTests(unittest.TestCase):
    """The helper tab behaves like the circles: filled cells are kept, only empty ones are filled."""
    ROWS = [log_row(4, "A", 60, 10), log_row(5, "A", 120, 20), log_row(6, "A", 60, 5)]

    def computed(self, today, columns=("A",), settings=None):
        return build_chart_tables(self.ROWS, list(columns), today, settings or ChartSettings())

    def stored_after_first_run(self, today=5, columns=("A",)):
        settings = ChartSettings()
        days, hours, cards = self.computed(today, columns)
        merged = merge_chart_data(days, hours, cards, list(columns), None, settings, overwrite=False)
        grid = chart_grid(merged.days, merged.columns, merged.hours, merged.cards, mode_marker(settings))
        return read_stored_data(as_sheet_text(grid))

    def test_round_trip_through_the_sheet(self):
        stored = self.stored_after_first_run()
        self.assertEqual(stored.students, ["A"])
        self.assertEqual(stored.hours, {(4, "a"): 1, (5, "a"): 3})
        self.assertEqual(stored.cards, {(4, "a"): 10, (5, "a"): 30})
        self.assertEqual((stored.hours_mode, stored.cards_mode), ("cumulative", "cumulative"))

    def test_a_filled_cell_is_never_replaced_and_new_days_are_added(self):
        stored = self.stored_after_first_run(today=5)
        stored.hours[(5, "a")] = 99                                  # somebody corrected / typed a value
        days, hours, cards = self.computed(today=7)
        merged = merge_chart_data(days, hours, cards, ["A"], stored, ChartSettings(), overwrite=False)
        self.assertEqual(merged.days, [4, 5, 6])                     # day 6 is new
        self.assertEqual(merged.hours["A"], [1, 99, 100.0])          # 99 survived; day 6 continues from it (+1 h that day)
        self.assertEqual((merged.kept, merged.added), (4, 2))

    def test_overwrite_rebuilds_from_the_log(self):
        stored = self.stored_after_first_run(today=5)
        stored.hours[(5, "a")] = 99
        days, hours, cards = self.computed(today=7)
        merged = merge_chart_data(days, hours, cards, ["A"], stored, ChartSettings(), overwrite=True)
        self.assertEqual(merged.hours["A"], [1, 3, 4.0])
        self.assertEqual(merged.kept, 0)

    def test_a_new_student_is_added_and_old_values_stay(self):
        stored = self.stored_after_first_run(today=5)
        rows = self.ROWS + [log_row(4, "B", 30, 7)]
        days, hours, cards = build_chart_tables(rows, ["A", "B"], 5, ChartSettings())
        merged = merge_chart_data(days, hours, cards, ["B", "A"], stored, ChartSettings(), overwrite=False)
        self.assertEqual(merged.columns, ["B", "A"])                 # the sheet's order decides the layout
        self.assertEqual(merged.hours["A"], [1, 3])
        self.assertEqual(merged.hours["B"], [0.5, 0.5])

    def test_a_student_who_left_keeps_their_data(self):
        stored = self.stored_after_first_run(today=5, columns=("A",))
        days, hours, cards = build_chart_tables([log_row(4, "B", 30, 7)], ["B"], 5, ChartSettings())
        merged = merge_chart_data(days, hours, cards, ["B"], stored, ChartSettings(), overwrite=False)
        self.assertEqual(merged.columns, ["B", "A"])
        self.assertEqual(merged.hours["A"], [1, 3])

    def test_switching_running_totals_rebuilds_only_that_block(self):
        stored = self.stored_after_first_run(today=5)
        stored.cards[(5, "a")] = 777                                 # a marker of "kept"
        per_day = ChartSettings(hours_cumulative=False)              # cards stay cumulative
        days, hours, cards = self.computed(today=6, settings=per_day)
        merged = merge_chart_data(days, hours, cards, ["A"], stored, per_day, overwrite=False)
        self.assertEqual(merged.hours["A"], [1.0, 2.0, 1.0])         # recomputed per day, not the old running totals
        self.assertEqual(merged.cards["A"], [10, 777, 782])         # untouched block keeps 777 and continues from it (+5)
        self.assertTrue(any("hours are now per-day" in note for note in merged.notes))

    def test_new_days_continue_from_hand_corrected_totals(self):
        """A student logged 400 instead of 40 cards for five days; the totals in the tab were fixed by hand."""
        wrong = [log_row(day, "M", 60, 400) for day in range(4, 9)] + [log_row(9, "M", 60, 40)]
        days, hours, cards = build_chart_tables(wrong, ["M"], today_number=10, settings=ChartSettings())
        self.assertEqual(cards["M"], [400, 800, 1200, 1600, 2000, 2040])       # what the (wrong) log says
        stored = self.stored_after_first_run(columns=("M",))
        stored.cards.clear()
        stored.cards.update({(day, "m"): 40 * (day - 3) for day in range(4, 9)})   # fixed by hand: 40 80 120 160 200
        merged = merge_chart_data(days, hours, cards, ["M"], stored, ChartSettings(), overwrite=False)
        self.assertEqual(merged.cards["M"], [40, 80, 120, 160, 200, 240])      # day 9 = 200 + 40, no jump to 2040

    def test_untouched_numbers_are_not_adjusted_at_all(self):
        """With nothing edited, new values are exactly what the log gives (no rounding drift)."""
        rows = [log_row(4, "A", 70, 1), log_row(5, "A", 50, 1), log_row(6, "A", 20, 1)]
        settings = ChartSettings()
        first = build_chart_tables(rows[:2], ["A"], 5, settings)
        stored_merge = merge_chart_data(*first, ["A"], None, settings, overwrite=False)
        stored = read_stored_data(as_sheet_text(chart_grid(stored_merge.days, ["A"], stored_merge.hours,
                                                           stored_merge.cards, mode_marker(settings))))
        full = build_chart_tables(rows, ["A"], 6, settings)
        merged = merge_chart_data(*full, ["A"], stored, settings, overwrite=False)
        self.assertEqual(merged.hours["A"], full[1]["A"])

    def test_per_day_values_never_depend_on_earlier_cells(self):
        per_day = ChartSettings(hours_cumulative=False, cards_cumulative=False)
        days, hours, cards = self.computed(today=7, settings=per_day)
        stored = self.stored_after_first_run(today=5)
        stored.hours_mode = stored.cards_mode = "per-day"
        stored.hours[(5, "a")] = 99
        merged = merge_chart_data(days, hours, cards, ["A"], stored, per_day, overwrite=False)
        self.assertEqual(merged.hours["A"], [1, 99, 1.0])              # day 6 is just that day's hour

    # --- late reports: the tab was written before the report arrived
    ON_TIME = [log_row(4, "A", 60, 10), log_row(6, "A", 60, 5)]                  # nothing for day 5 (yet)
    WITH_LATE = [log_row(4, "A", 60, 10), log_row(5, "A", 120, 20), log_row(6, "A", 60, 5)]

    def stored_from(self, rows, settings, today=7):
        days, hours, cards = build_chart_tables(rows, ["A"], today, settings)
        merged = merge_chart_data(days, hours, cards, ["A"], None, settings, overwrite=False)
        return read_stored_data(as_sheet_text(chart_grid(merged.days, ["A"], merged.hours, merged.cards,
                                                         mode_marker(settings))))

    def test_a_late_report_fills_the_empty_day_and_raises_the_running_totals_after_it(self):
        settings = ChartSettings()
        stored = self.stored_from(self.ON_TIME, settings)
        self.assertEqual(stored.hours, {(4, "a"): 1, (5, "a"): 1, (6, "a"): 2})        # day 5 held "nothing"
        days, hours, cards = build_chart_tables(self.WITH_LATE, ["A"], 7, settings)
        merged = merge_chart_data(days, hours, cards, ["A"], stored, settings, overwrite=False)
        self.assertEqual(merged.hours["A"], [1, 3, 4])                  # day 5 +2 h, and day 6 carries it on
        self.assertEqual(merged.cards["A"], [10, 30, 35])
        self.assertEqual(merged.late, {("A", 5): {"hours": 2.0, "cards": 20}})

    def test_a_late_report_is_counted_once(self):
        settings = ChartSettings()
        days, hours, cards = build_chart_tables(self.WITH_LATE, ["A"], 7, settings)
        first = merge_chart_data(days, hours, cards, ["A"], self.stored_from(self.ON_TIME, settings), settings, False)
        again = read_stored_data(as_sheet_text(chart_grid(first.days, ["A"], first.hours, first.cards, mode_marker(settings))))
        second = merge_chart_data(days, hours, cards, ["A"], again, settings, False)
        self.assertEqual((second.hours, second.cards, second.late), (first.hours, first.cards, {}))

    def test_a_late_report_in_per_day_mode_only_changes_its_own_day(self):
        settings = ChartSettings(hours_cumulative=False, cards_cumulative=False)
        stored = self.stored_from(self.ON_TIME, settings)
        days, hours, cards = build_chart_tables(self.WITH_LATE, ["A"], 7, settings)
        merged = merge_chart_data(days, hours, cards, ["A"], stored, settings, overwrite=False)
        self.assertEqual(merged.hours["A"], [1, 2, 1])
        self.assertEqual(merged.cards["A"], [10, 20, 5])
        self.assertEqual(set(merged.late), {("A", 5)})

    def test_a_day_without_any_report_is_not_a_late_report(self):
        settings = ChartSettings()
        stored = self.stored_from(self.ON_TIME, settings)
        days, hours, cards = build_chart_tables(self.ON_TIME, ["A"], 7, settings)
        merged = merge_chart_data(days, hours, cards, ["A"], stored, settings, overwrite=False)
        self.assertEqual(merged.late, {})

    def test_a_number_typed_by_hand_is_not_mistaken_for_a_late_report(self):
        settings = ChartSettings()
        stored = self.stored_from(self.WITH_LATE, settings)
        stored.hours[(5, "a")] = 2                                      # corrected by hand (the log says 3)
        days, hours, cards = build_chart_tables(self.WITH_LATE, ["A"], 7, settings)
        merged = merge_chart_data(days, hours, cards, ["A"], stored, settings, overwrite=False)
        self.assertEqual(merged.hours["A"][1], 2)
        self.assertEqual(merged.late, {})

    def test_tab_written_before_the_marker_existed_is_trusted(self):
        grid = [["יום", "A", "", "יום", "A"], ["4", "1", "", "4", "10"]]
        stored = read_stored_data(grid)
        self.assertIsNone(stored.hours_mode)
        days, hours, cards = self.computed(today=5)
        merged = merge_chart_data(days, hours, cards, ["A"], stored, ChartSettings(), overwrite=False)
        self.assertEqual(merged.hours["A"][0], 1)

    def test_not_our_layout_is_ignored(self):
        self.assertIsNone(read_stored_data([]))
        self.assertIsNone(read_stored_data([["something", "else"]]))
        self.assertIsNone(read_stored_data([["יום", "A", "B"]]))      # no second block

    def test_decimal_commas_and_thousands_separators(self):
        grid = [["יום", "A", "x", "יום", "A"], ["4", "2,08", "", "4", "1,234"]]
        stored = read_stored_data(grid)
        self.assertEqual(stored.hours[(4, "a")], 2.08)
        self.assertEqual(stored.cards[(4, "a")], 1234)


if __name__ == "__main__":
    unittest.main()
