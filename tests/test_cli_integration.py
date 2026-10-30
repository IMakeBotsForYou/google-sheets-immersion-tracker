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

    def run_cli(self, *extra, expect_exit=False):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            if expect_exit:
                with self.assertRaises(SystemExit) as caught:
                    cli.main(BASE_ARGS + list(extra))
                return output.getvalue(), caught.exception.code
            cli.main(BASE_ARGS + list(extra))
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
