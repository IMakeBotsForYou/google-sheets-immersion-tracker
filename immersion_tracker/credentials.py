"""Secrets and environment-specific values: read from the environment / a ``.env`` file, never from code.

SPREADSHEET_ID                 required - the id in the sheet's URL (docs.google.com/spreadsheets/d/<ID>/edit)
GOOGLE_SERVICE_ACCOUNT_FILE    path to the service-account key (default: credentials/service_account.json)
GOOGLE_SERVICE_ACCOUNT_JSON    the key's JSON itself, for servers / CI where a file is awkward (wins over the file)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError
from .paths import DEFAULT_SERVICE_ACCOUNT_FILE, ENV_FILE, LEGACY_SERVICE_ACCOUNT_FILE

ENV_SPREADSHEET_ID = "SPREADSHEET_ID"
ENV_SERVICE_ACCOUNT_FILE = "GOOGLE_SERVICE_ACCOUNT_FILE"
ENV_SERVICE_ACCOUNT_JSON = "GOOGLE_SERVICE_ACCOUNT_JSON"


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env file into os.environ.  Real environment variables win."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key:
            continue
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()        # an inline "# comment"
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class GoogleCredentials:
    spreadsheet_id: str
    service_account_file: Path | None = None
    service_account_info: dict | None = None

    def open_spreadsheet(self):
        """Authorise as the service account and open the spreadsheet."""
        import gspread
        if self.service_account_info is not None:
            client = gspread.service_account_from_dict(self.service_account_info)
        else:
            client = gspread.service_account(filename=str(self.service_account_file))
        return client.open_by_key(self.spreadsheet_id)


def load_credentials(root: Path) -> GoogleCredentials:
    """Read the credentials from the environment (call load_dotenv first).  Raises ConfigError with a hint."""
    spreadsheet_id = os.environ.get(ENV_SPREADSHEET_ID, "").strip()
    if not spreadsheet_id:
        raise ConfigError(f"{ENV_SPREADSHEET_ID} is not set - put it in {root / ENV_FILE} "
                          f"(copy .env.example) or export it in your shell.")

    inline_json = os.environ.get(ENV_SERVICE_ACCOUNT_JSON, "").strip()
    if inline_json:
        try:
            info = json.loads(inline_json)
        except json.JSONDecodeError as error:
            raise ConfigError(f"{ENV_SERVICE_ACCOUNT_JSON} is not valid JSON: {error}") from None
        return GoogleCredentials(spreadsheet_id, service_account_info=info)

    configured = os.environ.get(ENV_SERVICE_ACCOUNT_FILE, "").strip()
    candidates = [Path(configured).expanduser()] if configured else [DEFAULT_SERVICE_ACCOUNT_FILE, LEGACY_SERVICE_ACCOUNT_FILE]
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else root / candidate
        if path.is_file():
            return GoogleCredentials(spreadsheet_id, service_account_file=path)
    wanted = candidates[0] if candidates[0].is_absolute() else root / candidates[0]
    raise ConfigError(f"Service-account key not found at {wanted} - download it from Google Cloud "
                      f"(see the README) or set {ENV_SERVICE_ACCOUNT_FILE} / {ENV_SERVICE_ACCOUNT_JSON}.")
