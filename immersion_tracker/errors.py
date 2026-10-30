"""Exceptions for problems the user can fix (bad config, missing key, unreadable sheet...).

The command line prints their message and exits; they never show a traceback.
"""
from __future__ import annotations


class TrackerError(Exception):
    """An expected, user-fixable problem."""


class ConfigError(TrackerError):
    """Something is wrong in config.toml, .env or the credentials."""
