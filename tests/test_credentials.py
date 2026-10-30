import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from immersion_tracker.credentials import (ENV_SERVICE_ACCOUNT_FILE, ENV_SERVICE_ACCOUNT_JSON, ENV_SPREADSHEET_ID,
                                           load_credentials, load_dotenv)
from immersion_tracker.errors import ConfigError

KEYS = [ENV_SPREADSHEET_ID, ENV_SERVICE_ACCOUNT_FILE, ENV_SERVICE_ACCOUNT_JSON]


class EnvTestCase(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in KEYS:
            os.environ.pop(key, None)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)


class DotenvTests(EnvTestCase):
    def test_parsing(self):
        (self.root / ".env").write_text(
            '# comment\n\nSPREADSHEET_ID = abc123   # inline comment\nexport GOOGLE_SERVICE_ACCOUNT_FILE="keys/my key.json"\n'
            "BROKEN LINE\n", encoding="utf-8")
        load_dotenv(self.root / ".env")
        self.assertEqual(os.environ[ENV_SPREADSHEET_ID], "abc123")
        self.assertEqual(os.environ[ENV_SERVICE_ACCOUNT_FILE], "keys/my key.json")

    def test_real_environment_wins_over_the_file(self):
        os.environ[ENV_SPREADSHEET_ID] = "from-shell"
        (self.root / ".env").write_text("SPREADSHEET_ID=from-file\n", encoding="utf-8")
        load_dotenv(self.root / ".env")
        self.assertEqual(os.environ[ENV_SPREADSHEET_ID], "from-shell")

    def test_missing_file_is_fine(self):
        load_dotenv(self.root / "nope.env")


class LoadCredentialsTests(EnvTestCase):
    def test_spreadsheet_id_is_required(self):
        with self.assertRaisesRegex(ConfigError, "SPREADSHEET_ID"):
            load_credentials(self.root)

    def test_key_file_default_location(self):
        os.environ[ENV_SPREADSHEET_ID] = "id"
        (self.root / "credentials").mkdir()
        (self.root / "credentials" / "service_account.json").write_text("{}", encoding="utf-8")
        credentials = load_credentials(self.root)
        self.assertEqual(credentials.service_account_file, self.root / "credentials" / "service_account.json")

    def test_legacy_location_next_to_the_script_still_works(self):
        os.environ[ENV_SPREADSHEET_ID] = "id"
        (self.root / "service_account.json").write_text("{}", encoding="utf-8")
        self.assertEqual(load_credentials(self.root).service_account_file, self.root / "service_account.json")

    def test_inline_json_wins_over_files(self):
        os.environ[ENV_SPREADSHEET_ID] = "id"
        os.environ[ENV_SERVICE_ACCOUNT_JSON] = json.dumps({"type": "service_account"})
        (self.root / "service_account.json").write_text("{}", encoding="utf-8")
        credentials = load_credentials(self.root)
        self.assertEqual(credentials.service_account_info, {"type": "service_account"})
        self.assertIsNone(credentials.service_account_file)

    def test_bad_inline_json_and_missing_key(self):
        os.environ[ENV_SPREADSHEET_ID] = "id"
        with self.assertRaisesRegex(ConfigError, "Service-account key not found"):
            load_credentials(self.root)
        os.environ[ENV_SERVICE_ACCOUNT_JSON] = "{not json"
        with self.assertRaisesRegex(ConfigError, "not valid JSON"):
            load_credentials(self.root)


if __name__ == "__main__":
    unittest.main()
