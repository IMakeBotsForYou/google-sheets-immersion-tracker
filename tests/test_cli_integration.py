"""End to end: the real command line against a fake Google Sheet (see fake_gspread.py)."""
import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fake_gspread
from immersion_tracker import cli

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
TODAY = ["--today", "2026-11-01 12:00"]
EARLY_TODAY = ["--today", "2026-10-31 12:00"]
BASE_ARGS = [str(EXAMPLES / "sample_chat.txt"), "--config", str(EXAMPLES / "demo.toml"),
             "--people", str(EXAMPLES / "demo_people.json"), "--no-pause"]


class CliTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        (self.home / ".env").write_text('SPREADSHEET_ID=test-sheet\nGOOGLE_SERVICE_ACCOUNT_JSON={"type": "service_account"}\n',
                                        encoding="utf-8")
        for patcher in (mock.patch.dict(os.environ, {"IMMERSION_TRACKER_HOME": str(self.home)}),
                        mock.patch.dict(sys.modules)):
            patcher.start()
            self.addCleanup(patcher.stop)
        for key in ("SPREADSHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SERVICE_ACCOUNT_FILE"):
            os.environ.pop(key, None)

    def run_cli(self, *extra, expect_exit=False, chat=None):
        args = BASE_ARGS if chat is None else [str(chat)] + BASE_ARGS[1:]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            if expect_exit:
                with self.assertRaises(SystemExit) as caught:
                    cli.main(args + list(extra))
                return output.getvalue(), caught.exception.code
            cli.main(args + list(extra))
        return output.getvalue(), None

    def install_sheet(self, student_order):
        self.book = fake_gspread.make_book(student_order)
        fake_gspread.install(self.book)
        return self.book

    @staticmethod
    def names_in_order(output, names, after):
        text = output.split(after, 1)[1]
        positions = {name: text.index(f"\n{name} ") for name in names}
        return sorted(names, key=positions.get)

    def tab(self, title):
        return next(sheet for sheet in self.book.sheets if sheet.title == title)


class WritingTests(CliTestCase):
    def test_writes_cells_log_and_charts_in_the_order_of_the_sheet(self):
        order = ["Dan", "Alice", "Chloe", "Ben"]                     # NOT the order of the people file
        self.install_sheet(order)
        output, _ = self.run_cli(*TODAY)

        self.assertEqual(self.names_in_order(output, order, "=== week 2 ==="), order)
        week = self.tab("חשיפה")
        alice_col = order.index("Alice") + 1
        self.assertEqual(week.grid[(10, alice_col)], "◯◯◯◯")           # Sunday 25/10, week 2 table starts at row 9
        self.assertEqual(week.grid[(10 + 3, order.index("Dan") + 1)], "✖")   # Dan's unreadable report on Wed 28/10

        log = self.tab("יומן חשיפה").get_all_values()
        self.assertEqual(len(log) - 1, 25)
        self.assertEqual([row[2] for row in log[1:5]], order[:])    # first day: sheet order
        self.assertEqual(len(self.book.charts), 2)
        top, bottom = (c["position"]["overlayPosition"] for c in self.book.charts)
        self.assertEqual(top["anchorCell"]["columnIndex"], bottom["anchorCell"]["columnIndex"])
        self.assertEqual(top["widthPixels"], bottom["widthPixels"])
        self.assertEqual(self.tab("נתוני גרפים").get_all_values()[0][:5], ["יום", *order])

    def test_a_second_run_changes_nothing_and_does_not_duplicate(self):
        self.install_sheet(["Alice", "Ben", "Chloe", "Dan"])
        self.run_cli(*TODAY)
        first = ({t.title: dict(t.grid) for t in self.book.sheets}, len(self.book.charts))
        output, _ = self.run_cli(*TODAY)
        self.assertEqual(({t.title: dict(t.grid) for t in self.book.sheets}, len(self.book.charts)), first)
        self.assertIn("Left", output)                                # already-filled cells are left alone

    def test_reordering_the_sheet_reorders_the_output_without_any_code_change(self):
        self.install_sheet(["Ben", "Dan", "Alice", "Chloe"])
        output, _ = self.run_cli(*TODAY, "--dry-run")
        self.assertEqual(self.names_in_order(output, ["Ben", "Dan", "Alice", "Chloe"], "=== week 2 ==="),
                         ["Ben", "Dan", "Alice", "Chloe"])


class LateReportTests(CliTestCase):
    """A report that arrives after its day was already closed with ✖ still counts - with a warning."""
    ORDER = ["Alice", "Ben", "Chloe", "Dan"]

    def setUp(self):
        super().setUp()
        self.install_sheet(self.ORDER)
        full = (EXAMPLES / "sample_chat.txt").read_text(encoding="utf-8")
        chloe_day_9 = re.compile(r"^\[10/\d+/26, [^\]]+\] Chloe Mizrahi: סיכום יום 9\n(?:(?!\[\d).*\n)*", re.M)
        self.assertRegex(full, chloe_day_9)
        self.full_chat, self.early_chat = self.home / "full.txt", self.home / "early.txt"
        self.full_chat.write_text(full, encoding="utf-8")
        self.early_chat.write_text(chloe_day_9.sub("", full), encoding="utf-8")     # she hasn't posted day 9 yet

    def chloe_cell(self):
        return self.tab("חשיפה").grid[(9 + 1 + 5, 1 + self.ORDER.index("Chloe"))]    # week 2, Friday 30/10 = day 9

    def chart(self, day, block):
        grid = self.tab("נתוני גרפים").get_all_values()
        start = 1 if block == "hours" else grid[0].index("יום", 1) + 1
        row = next(r for r in grid if r and r[0] == str(day))
        return float(row[start + grid[0][start:].index("Chloe")])

    def test_a_late_report_counts_in_the_week_table_and_the_chart_data_with_a_warning(self):
        self.run_cli(*EARLY_TODAY, chat=self.early_chat)
        self.assertEqual(self.chloe_cell(), "✖")                       # day 9 closed with nothing reported
        hours_before = {day: self.chart(day, "hours") for day in (8, 9, 10)}
        cards_before = {day: self.chart(day, "cards") for day in (8, 9, 10)}

        output, _ = self.run_cli(*TODAY, chat=self.full_chat)         # ...and now her report is in the chat
        self.assertEqual(self.chloe_cell(), "◯◯◯◯◯")                  # 335 minutes
        self.assertIn("late report(s) counted - the sheet already had ✖", output)
        self.assertIn("Chloe Fri 30/10: ✖ -> ◯◯◯◯◯", output)
        self.assertIn("Chloe day 9: +335 min, +34 Anki cards", output)
        for day in (9, 10):                                            # day 9 itself, and the totals after it
            self.assertAlmostEqual(self.chart(day, "hours"), hours_before[day] + 335 / 60, delta=0.02)   # sheet shows 2 decimals
            self.assertEqual(self.chart(day, "cards"), cards_before[day] + 34)
        self.assertEqual(self.chart(8, "hours"), hours_before[8])      # earlier days untouched

    def test_it_is_counted_once_and_a_third_run_changes_nothing(self):
        self.run_cli(*EARLY_TODAY, chat=self.early_chat)
        self.run_cli(*TODAY, chat=self.full_chat)
        snapshot = {t.title: dict(t.grid) for t in self.book.sheets}
        output, _ = self.run_cli(*TODAY, chat=self.full_chat)
        self.assertNotIn("late report", output)
        self.assertEqual({t.title: dict(t.grid) for t in self.book.sheets}, snapshot)

    def test_a_dry_run_says_what_would_happen_and_writes_nothing(self):
        self.run_cli(*EARLY_TODAY, chat=self.early_chat)
        output, _ = self.run_cli(*TODAY, "--dry-run", chat=self.full_chat)
        self.assertIn("1 late report(s) would be counted", output)
        self.assertEqual(self.chloe_cell(), "✖")

    def test_a_cross_with_no_report_behind_it_is_left_alone(self):
        output, _ = self.run_cli(*TODAY, chat=self.early_chat)
        self.assertNotIn("late report", output)


class ChartDataIsAddOnlyTests(CliTestCase):
    """The chart data tab keeps what it already holds, exactly like the circles in the week tables."""
    ORDER = ["Alice", "Ben", "Chloe", "Dan"]

    def setUp(self):
        super().setUp()
        self.install_sheet(self.ORDER)

    def data(self):
        return self.tab("נתוני גרפים").get_all_values()

    def locate(self, day, student, block=0):
        """(row, column) of a cell in the helper tab."""
        grid = self.data()
        row = next(i for i, r in enumerate(grid) if r and r[0] == str(day))
        header = grid[0]
        start = 1 if block == 0 else header.index("יום", 1) + 1
        return row, start + header[start:].index(student)

    def test_new_days_are_appended_and_old_rows_untouched(self):
        self.run_cli("--today", "2026-10-29 12:00")                  # days 4..8
        first = self.data()
        self.run_cli(*TODAY)                                         # days 4..10
        second = self.data()
        self.assertEqual(len(first) - 1, 5)
        self.assertEqual(len(second) - 1, 7)
        self.assertEqual(second[:len(first)], first)                 # nothing above was touched

    def test_an_edited_cell_survives_a_run_and_overwrite_restores_it(self):
        self.run_cli(*TODAY)
        row, col = self.locate(5, "Alice")
        original = self.data()[row][col]
        self.tab("נתוני גרפים").grid[(row, col)] = 99                # the user types a value
        self.run_cli(*TODAY)
        self.assertEqual(self.data()[row][col], "99")
        output, _ = self.run_cli(*TODAY, "--overwrite")
        self.assertEqual(self.data()[row][col], original)
        self.assertIn("rebuilt from the log", output)

    def test_a_new_student_is_added_without_touching_the_others(self):
        subset = self.home / "three.json"
        subset.write_text('{"students": {"Alice Cohen": "Alice", "Ben Levi": "Ben", "Chloe Mizrahi": "Chloe"}}', encoding="utf-8")
        self.run_cli(*TODAY, "--people", str(subset))
        before = self.data()
        self.assertNotIn("Dan", before[0])
        row, col = self.locate(6, "Ben")
        self.tab("נתוני גרפים").grid[(row, col)] = 55                # make Ben's value recognisable
        self.run_cli(*TODAY)                                         # Dan joins
        after = self.data()
        self.assertIn("Dan", after[0])
        row, col = self.locate(6, "Ben")
        self.assertEqual(after[row][col], "55")                      # kept, although the columns moved
        self.assertEqual(len(self.book.charts), 2)

    def test_a_student_removed_from_the_people_file_keeps_their_data(self):
        self.run_cli(*TODAY)
        row, col = self.locate(7, "Dan")
        value = self.data()[row][col]
        subset = self.home / "three.json"
        subset.write_text('{"students": {"Alice Cohen": "Alice", "Ben Levi": "Ben", "Chloe Mizrahi": "Chloe"}}', encoding="utf-8")
        self.run_cli(*TODAY, "--people", str(subset))
        row, col = self.locate(7, "Dan")
        self.assertEqual(self.data()[row][col], value)

    def test_switching_to_per_day_hours_rebuilds_the_hours_block_only(self):
        self.run_cli(*TODAY)
        row, col = self.locate(8, "Alice", block=1)
        self.tab("נתוני גרפים").grid[(row, col)] = 4242              # a cards cell to watch
        config = self.home / "per_day.toml"
        config.write_text((EXAMPLES / "demo.toml").read_text(encoding="utf-8") + "\n[charts]\nhours_cumulative = false\n",
                          encoding="utf-8")
        output, _ = self.run_cli(*TODAY, "--config", str(config))
        self.assertIn("hours are now per-day", output)
        row, col = self.locate(8, "Alice", block=1)
        self.assertEqual(self.data()[row][col], "4242")              # cards untouched
        hours_row, hours_col = self.locate(8, "Alice")
        self.assertLess(float(self.data()[hours_row][hours_col]), 10)    # a day's hours, not a running total (~19)

    def test_the_summary_line_says_what_happened(self):
        output, _ = self.run_cli(*TODAY)
        self.assertIn("Chart data: kept 0 filled cells, added 56 new ones", output)
        output, _ = self.run_cli(*TODAY)
        self.assertIn("Chart data: kept 56 filled cells, added 0 new ones", output)


class LogIsAddOnlyTests(CliTestCase):
    """The log tab keeps rows that are already there, so a value corrected by hand stays corrected."""
    ORDER = ["Alice", "Ben", "Chloe", "Dan"]

    def setUp(self):
        super().setUp()
        self.install_sheet(self.ORDER)

    def log(self):
        return self.tab("יומן חשיפה").get_all_values()

    def log_cell(self, date, student, column_name):
        grid = self.log()
        header = grid[0]
        row = next(i for i, r in enumerate(grid) if r[0] == date and r[2] == student)
        return row, header.index(column_name)

    def test_a_hand_corrected_log_value_survives_and_feeds_the_charts(self):
        self.run_cli(*TODAY)
        row, col = self.log_cell("2026-10-27", "Alice", "אנקי")
        original = int(self.log()[row][col])
        self.tab("יומן חשיפה").grid[(row, col)] = original + 1000        # the log said 22, now it says 1022
        output, _ = self.run_cli(*TODAY)
        self.assertEqual(self.log()[row][col], str(original + 1000))     # not reset to what the chat says
        self.assertIn("1 differ from the chat", output)
        # a student's chart data is rebuilt from the corrected log
        self.run_cli(*TODAY, "--rebuild-charts")
        data = self.tab("נתוני גרפים").get_all_values()
        header = data[0]
        cards_start = header.index("יום", 1) + 1
        alice = cards_start + header[cards_start:].index("Alice")
        day6 = next(r for r in data if r and r[0] == "6")
        self.assertGreater(int(day6[alice]), 1000)
        self.assertEqual(self.log()[row][col], str(original + 1000))     # --rebuild-charts leaves the log alone

    def test_new_rows_are_still_added(self):
        subset = self.home / "two.json"
        subset.write_text('{"students": {"Alice Cohen": "Alice", "Ben Levi": "Ben"}}', encoding="utf-8")
        self.run_cli(*TODAY, "--people", str(subset))
        before = len(self.log()) - 1
        output, _ = self.run_cli(*TODAY)                                 # Chloe and Dan join
        self.assertGreater(len(self.log()) - 1, before)
        self.assertEqual(len(self.log()) - 1, 25)
        self.assertIn("new rows added", output)

    def test_overwrite_replaces_log_rows_with_the_chats_version(self):
        self.run_cli(*TODAY)
        row, col = self.log_cell("2026-10-27", "Alice", "אנקי")
        original = self.log()[row][col]
        self.tab("יומן חשיפה").grid[(row, col)] = 5000
        self.run_cli(*TODAY, "--overwrite")
        self.assertEqual(self.log()[row][col], original)

    def test_fixing_only_the_chart_data_no_longer_causes_a_jump(self):
        """Hand-corrected running totals in the chart data; later days must continue from them."""
        self.run_cli("--today", "2026-10-29 12:00")                      # days 4..8
        data_tab = self.tab("נתוני גרפים")
        grid = data_tab.get_all_values()
        header = grid[0]
        cards_start = header.index("יום", 1) + 1
        chloe = cards_start + header[cards_start:].index("Chloe")
        last_row = max(i for i, r in enumerate(grid) if r and r[0].isdigit())
        data_tab.grid[(last_row, chloe)] = 10                            # day 8's total corrected by hand to 10
        self.run_cli(*TODAY)                                             # days 9, 10 are new
        data = data_tab.get_all_values()
        day9 = next(r for r in data if r and r[0] == "9")
        day10 = next(r for r in data if r and r[0] == "10")
        self.assertEqual(day10[chloe], str(10 + 34 + 44))                # 10 + the log's cards for days 9 and 10
        self.assertEqual(day9[chloe], str(10 + 34))


class DryRunTests(CliTestCase):
    def test_offline_never_touches_google_and_uses_the_people_file_order(self):
        sys.modules["gspread"] = None                                # any "import gspread" now fails
        output, _ = self.run_cli(*TODAY, "--offline")
        self.assertEqual(self.names_in_order(output, ["Alice", "Ben", "Chloe", "Dan"], "=== week 2 ==="),
                         ["Alice", "Ben", "Chloe", "Dan"])
        self.assertIn("Chart colours", output)
        self.assertNotIn("couldn't read the sheet", output)

    def test_dry_run_falls_back_when_the_sheet_cannot_be_read(self):
        (self.home / ".env").write_text("", encoding="utf-8")        # no credentials
        output, _ = self.run_cli(*TODAY, "--dry-run")
        self.assertIn("couldn't read the sheet", output)
        self.assertIn("=== week 2 ===", output)

    def test_dry_run_does_not_write(self):
        self.install_sheet(["Alice", "Ben", "Chloe", "Dan"])
        self.run_cli(*TODAY, "--dry-run")
        self.assertEqual(self.book.batches, [])
        self.assertEqual([s.title for s in self.book.sheets], ["חשיפה"])


class ProblemTests(CliTestCase):
    def test_real_run_without_credentials_explains_what_is_missing(self):
        (self.home / ".env").write_text("", encoding="utf-8")
        output, code = self.run_cli(*TODAY, expect_exit=True)
        self.assertIn("SPREADSHEET_ID", str(code))

    def test_unknown_config_key_is_reported_not_a_traceback(self):
        bad = self.home / "bad.toml"
        bad.write_text("[calendar]\nday_end = '05:00'\n", encoding="utf-8")
        output, code = self.run_cli("--config", str(bad), "--offline", expect_exit=True)
        self.assertIn("unknown key", str(code))

    def test_list_senders(self):
        output, _ = self.run_cli("--list-senders")
        self.assertIn("Alice Cohen", output)
        self.assertNotIn("<-- not classified", output)


if __name__ == "__main__":
    unittest.main()
