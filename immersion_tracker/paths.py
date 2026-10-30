"""Where the project's local (never committed) files live."""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = ".env"
CONFIG_FILE = "config.toml"
PEOPLE_FILE = "people.json"
DEFAULT_SERVICE_ACCOUNT_FILE = Path("credentials") / "service_account.json"
LEGACY_SERVICE_ACCOUNT_FILE = Path("service_account.json")     # where the first version of the script looked

HOME_ENV_VAR = "IMMERSION_TRACKER_HOME"


def project_root() -> Path:
    """The folder holding .env, config.toml, people.json and credentials/.

    The repository folder by default; set IMMERSION_TRACKER_HOME to keep those files somewhere else.
    """
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent
