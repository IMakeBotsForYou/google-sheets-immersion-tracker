"""End to end: the real command line against a fake Google Sheet (see fake_gspread.py)."""
import contextlib
import io
import os
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
        args = BASE_ARGS + list(extra)
        if chat:
            args[0] = str(chat)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            if expect_exit:
                with self.assertRaises(SystemExit) as caught:
                    cli.main(args)
                return output.getvalue(), caught.exception.code
            cli.main(args)
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
        self.assertIn(f"2026-10-27 Alice: the sheet has", output)
        self.assertIn(f"{original + 1000} Anki cards", output)
        self.assertIn("; the chat says", output)
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


class ConjugationTabTests(CliTestCase):
    """"הטיות 40" lines go to a tab of their own: 20 = one circle, 40 = two, less than 20 = a cross."""
    ORDER = ["Alice", "Ben", "Chloe", "Dan"]
    TITLE = "הטיות"

    def setUp(self):
        super().setUp()
        self.install_sheet(self.ORDER)

    def add_tab(self):
        return fake_gspread.add_week_tab(self.book, self.TITLE, self.ORDER, first_week=2, weeks=2,
                                         name_template="הטיות שבוע {week}")

    def cell(self, tab, student, day_of_october):
        """Row 1 of the first table is Sunday 25/10 (the demo's week 2)."""
        return tab.grid.get((1 + day_of_october - 25, 1 + self.ORDER.index(student)))

    def test_circles_and_crosses_are_written(self):
        tab = self.add_tab()
        output, _ = self.run_cli(*TODAY)
        self.assertEqual(self.cell(tab, "Alice", 25), "◯◯")        # 40-59 exercises
        self.assertEqual(self.cell(tab, "Alice", 26), "✖")          # below 20 (or no line)
        self.assertEqual(self.cell(tab, "Chloe", 31), "◯◯")
        self.assertEqual(self.cell(tab, "Dan", 31), "◯◯◯")          # 60+
        self.assertEqual(self.cell(tab, "Chloe", 27), "✖")          # Chloe sent no report that day
        self.assertIn("[הטיות] Updated", output)
        self.assertEqual(self.tab("חשיפה").grid[(10, 1)], "◯◯◯◯")    # the main tab is unchanged

    def test_filled_cells_are_left_alone_unless_overwrite(self):
        tab = self.add_tab()
        tab.grid[(1, 1)] = "◯◯◯◯◯"
        self.run_cli(*TODAY)
        self.assertEqual(tab.grid[(1, 1)], "◯◯◯◯◯")
        self.run_cli(*TODAY, "--overwrite")
        self.assertEqual(tab.grid[(1, 1)], "◯◯")

    def test_a_missing_tab_is_not_fatal(self):
        output, _ = self.run_cli(*TODAY)
        self.assertIn("no 'הטיות' tab in the sheet", output)
        self.assertEqual(self.tab("חשיפה").grid[(10, 1)], "◯◯◯◯")    # everything else was still written
        self.assertEqual(len(self.book.charts), 2)

    def test_tables_that_dont_exist_yet_are_reported_not_fatal(self):
        tab = fake_gspread.add_week_tab(self.book, self.TITLE, self.ORDER, first_week=3, weeks=1,
                                        name_template="הטיות שבוע {week}")        # nothing for week 2
        output, _ = self.run_cli(*TODAY)
        self.assertIn("no table for week [2]", output)
        self.assertEqual(self.tab("חשיפה").grid[(10, 1)], "◯◯◯◯")

    def test_a_chat_without_any_conjugation_line_writes_nothing_there(self):
        chat = self.home / "plain.txt"
        chat.write_text("".join(line for line in (EXAMPLES / "sample_chat.txt").read_text(encoding="utf-8").splitlines(True)
                                if not line.startswith("הטיות")), encoding="utf-8")
        tab = self.add_tab()
        output, _ = self.run_cli(*TODAY, chat=chat)
        self.assertEqual(tab.grid.get((1, 1)), None)                 # not even crosses: nobody uses the feature
        self.assertNotIn("הטיות שבוע", output)

    def test_it_can_be_switched_off(self):
        config = self.home / "off.toml"
        config.write_text((EXAMPLES / "demo.toml").read_text(encoding="utf-8").replace("first_week = 2", "enabled = false"),
                          encoding="utf-8")
        tab = self.add_tab()
        output, _ = self.run_cli(*TODAY, "--config", str(config))
        self.assertEqual(tab.grid.get((1, 1)), None)
        self.assertNotIn("הטיות שבוע", output)

    def test_the_dry_run_previews_the_tab_without_the_sheet(self):
        sys.modules["gspread"] = None
        output, _ = self.run_cli(*TODAY, "--offline")
        self.assertIn("=== הטיות שבוע 2 ===", output)
        self.assertEqual(self.names_in_order(output, ["Alice", "Ben", "Chloe", "Dan"], "=== הטיות שבוע 2 ==="),
                         ["Alice", "Ben", "Chloe", "Dan"])


class WarningTests(CliTestCase):
    def test_free_text_in_a_report_is_ignored_with_a_named_warning(self):
        sys.modules["gspread"] = None
        output, _ = self.run_cli(*TODAY, "--offline")
        self.assertIn("Alice: ignored a line that isn't a report line (not counted)", output)
        self.assertIn("אולי אוסיף עוד קצת אנקי בלילה", output)
        self.assertNotIn("Alice Cohen", output)


class LateReportTests(CliTestCase):
    """A report for a day that was already crossed out fills that day in; circles already there are never replaced."""
    ORDER = ["Alice", "Ben", "Chloe", "Dan"]
    LATE = ("[10/29/26, 9:00:00 PM] Chloe Mizrahi: סיכום יום 6\nצפייה 60 דקות\nקריאה 60 דקות\n"
            "שמיעה 60 דקות\nרילז 60 דקות\nהטיות 40\n")          # Day 6 = Tue 27/10, sent two days late: 4 h, 40 exercises
    MAIN_CHLOE_TUE = (12, 3)            # week 2 table starts at row 9; Sunday 25/10 is row 10, Tuesday row 12; Chloe is column 3
    CONJ_CHLOE_TUE = (3, 3)

    def setUp(self):
        super().setUp()
        self.install_sheet(self.ORDER)
        self.late_chat = self.home / "late.txt"
        self.late_chat.write_text((EXAMPLES / "sample_chat.txt").read_text(encoding="utf-8") + self.LATE, encoding="utf-8")

    def test_a_late_report_replaces_the_cross(self):
        self.run_cli(*TODAY)
        main = self.tab("חשיפה")
        self.assertEqual(main.grid[self.MAIN_CHLOE_TUE], "✖")           # Chloe sent nothing for Tuesday
        before = dict(main.grid)
        output, _ = self.run_cli(*TODAY, chat=self.late_chat)
        self.assertEqual(main.grid[self.MAIN_CHLOE_TUE], "◯◯◯◯")
        self.assertEqual({k: v for k, v in main.grid.items() if k != self.MAIN_CHLOE_TUE},
                         {k: v for k, v in before.items() if k != self.MAIN_CHLOE_TUE})      # nothing else moved
        self.assertIn("Filled in 1 late report(s) over a cross", output)
        self.assertIn("Chloe 2026-10-27: ✖ -> ◯◯◯◯", output)

    def test_the_late_report_is_added_to_the_log_with_a_hint_about_the_charts(self):
        self.run_cli(*TODAY)
        output, _ = self.run_cli(*TODAY, chat=self.late_chat)
        rows = self.tab("יומן חשיפה").get_all_values()
        self.assertTrue(any(r[0] == "2026-10-27" and r[2] == "Chloe" and r[-1] == "240" for r in rows))
        self.assertIn("late reports", output)
        self.assertIn("--rebuild-charts", output)

    def test_a_late_report_also_fills_the_conjugations_tab(self):
        tab = fake_gspread.add_week_tab(self.book, "הטיות", self.ORDER, first_week=2, weeks=2, name_template="הטיות שבוע {week}")
        self.run_cli(*TODAY)
        self.assertEqual(tab.grid[self.CONJ_CHLOE_TUE], "✖")
        output, _ = self.run_cli(*TODAY, chat=self.late_chat)
        self.assertEqual(tab.grid[self.CONJ_CHLOE_TUE], "◯◯")
        self.assertIn("[הטיות] Filled in 1 late report(s) over a cross", output)

    def test_circles_are_kept_and_a_different_chat_gives_a_warning(self):
        self.run_cli(*TODAY)
        main = self.tab("חשיפה")
        main.grid[(10, 1)] = "◯"                                        # Alice on Sunday: the chat says ◯◯◯◯
        output, _ = self.run_cli(*TODAY)
        self.assertEqual(main.grid[(10, 1)], "◯")
        self.assertIn("WARNING: Alice 2026-10-25: the sheet already shows ◯ but the chat says ◯◯◯◯ - left alone", output)

    def test_an_unchanged_rerun_has_no_cell_warnings(self):
        self.run_cli(*TODAY)
        output, _ = self.run_cli(*TODAY)
        self.assertNotIn("already shows", output)
        self.assertNotIn("late report", output)

    def test_overwrite_still_replaces_circles(self):
        self.run_cli(*TODAY)
        main = self.tab("חשיפה")
        main.grid[(10, 1)] = "◯"
        self.run_cli(*TODAY, "--overwrite")
        self.assertEqual(main.grid[(10, 1)], "◯◯◯◯")

    def test_the_dry_run_says_what_would_be_filled_in_without_writing(self):
        self.run_cli(*TODAY)
        batches = len(self.book.batches)
        output, _ = self.run_cli(*TODAY, "--dry-run", chat=self.late_chat)
        self.assertIn("Would fill in 1 late report(s) over a cross", output)
        self.assertIn("Chloe 2026-10-27: ✖ -> ◯◯◯◯", output)
        self.assertEqual(len(self.book.batches), batches)
        self.assertEqual(self.tab("חשיפה").grid[self.MAIN_CHLOE_TUE], "✖")


class LogConjugationsColumnTests(CliTestCase):
    """The log tab gets a הטיות column before the total; an existing log is migrated, never refused or emptied."""
    ORDER = ["Alice", "Ben", "Chloe", "Dan"]
    TITLE = "יומן חשיפה"

    def setUp(self):
        super().setUp()
        self.install_sheet(self.ORDER)

    def log(self):
        return self.tab(self.TITLE).get_all_values()

    def drop_conjugations_column(self, placeholder=False):
        """Turn the log tab into the layout before the column existed (or into the user's layout: an empty header cell)."""
        tab = self.tab(self.TITLE)
        grid = tab.get_all_values()
        at = grid[0].index("הטיות")
        tab.grid = {}
        for r, row in enumerate(grid):
            cells = list(row)
            if placeholder:
                cells[at] = ""                                       # the cell stays, but empty
            else:
                del cells[at]
            for c, value in enumerate(cells):
                if value != "":
                    tab.grid[(r, c)] = value
        return at

    def test_the_header_and_rows_have_the_column_before_the_total(self):
        self.run_cli(*TODAY)
        header = self.log()[0]
        self.assertEqual(header[-3:], ["אנקי", "הטיות", "סך הכל (דקות)"])
        row = next(r for r in self.log()[1:] if r[0] == "2026-10-25" and r[2] == "Alice")
        self.assertEqual(int(row[-1]), sum(int(x) for x in row[3:7] if x))     # the total is the four activities only
        self.assertNotEqual(row[-2], "")

    def test_an_old_log_is_migrated_and_keeps_every_value(self):
        self.run_cli(*TODAY)
        row_index = next(i for i, r in enumerate(self.log()) if r[0] == "2026-10-27" and r[2] == "Alice")
        anki_col = self.log()[0].index("אנקי")
        self.tab(self.TITLE).grid[(row_index, anki_col)] = 777            # a hand correction
        self.drop_conjugations_column()
        self.assertNotIn("הטיות", self.log()[0])
        output, _ = self.run_cli(*TODAY)
        grid = self.log()
        self.assertEqual(grid[0][-3:], ["אנקי", "הטיות", "סך הכל (דקות)"])
        self.assertEqual(len(grid) - 1, 25)
        self.assertEqual(grid[row_index][anki_col], "777")                # the correction survived the migration
        self.assertNotEqual(grid[row_index][-2], "")                      # the empty conjugations cell was filled in
        self.assertIn("empty 'הטיות' cell(s)", output)
        self.assertNotIn("doesn't look like this script's log", output)

    def test_a_log_with_an_empty_header_cell_for_the_column_is_accepted(self):
        """The layout from the user's sheet:  ... אנקי | (empty) | סך הכל (דקות)"""
        self.run_cli(*TODAY)
        self.drop_conjugations_column(placeholder=True)
        for key in [k for k in self.tab(self.TITLE).grid if k[1] == self.log()[0].index("") and k[0] > 0]:
            del self.tab(self.TITLE).grid[key]
        self.assertEqual(self.log()[0][-2], "")
        self.run_cli(*TODAY)
        self.assertEqual(self.log()[0][-2], "הטיות")
        self.assertTrue(all(row[-2] != "" for row in self.log()[1:] if row[0] == "2026-10-25" and row[2] == "Alice"))

    def test_a_hand_entered_value_in_the_column_is_never_replaced(self):
        self.run_cli(*TODAY)
        row_index = next(i for i, r in enumerate(self.log()) if r[0] == "2026-10-26" and r[2] == "Ben")
        conj_col = self.log()[0].index("הטיות")
        self.tab(self.TITLE).grid[(row_index, conj_col)] = 99
        output, _ = self.run_cli(*TODAY)
        self.assertEqual(self.log()[row_index][conj_col], "99")
        self.assertIn("99 conjugations", output)                          # reported as differing from the chat

    def test_a_tab_that_is_not_a_log_is_still_left_alone(self):
        tab = fake_gspread.FakeWorksheet(self.TITLE, rows=10, cols=4)
        tab.grid = {(0, 0): "name", (0, 1): "score", (1, 0): "x", (1, 1): "1"}
        self.book.sheets.append(tab)
        output, _ = self.run_cli(*TODAY)
        self.assertIn("doesn't look like this script's log", output)
        self.assertEqual(tab.grid, {(0, 0): "name", (0, 1): "score", (1, 0): "x", (1, 1): "1"})


class FollowUpMessageTests(CliTestCase):
    """A later message with only a conjugations / Anki line adds to the day; it never wipes the day's minutes."""
    CHAT = ("[10/25/26, 8:00:00 PM] Alice Cohen: סיכום יום 4\nצפייה 60 דקות\nקריאה 60 דקות\nשמיעה 60 דקות\n"
            "[10/25/26, 11:00:00 PM] Alice Cohen: סיכום יום 4\nהטיות 40\n")

    def test_the_day_keeps_its_minutes_and_gains_the_conjugations(self):
        chat = self.home / "follow_up.txt"
        chat.write_text(self.CHAT, encoding="utf-8")
        sys.modules["gspread"] = None
        output, _ = self.run_cli("--today", "2026-10-27 12:00", "--offline", chat=chat)
        alice_week = next(line for line in output.splitlines() if line.startswith("Alice"))
        self.assertIn("◯◯◯", alice_week)                                   # 180 minutes: three circles, not a cross
        self.assertRegex(output, r"Alice\s*\|\s*60\s*\|\s*60\s*\|\s*60\s*\|\s*-\s*\|\s*-\s*\|\s*40\s*\|\s*180")


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
