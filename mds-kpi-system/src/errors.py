"""Errors that matter to the fail-loud rule.

A SourceError means we could not get trustworthy data out of a source system
this week. It never gets swallowed into a zero. It becomes a failed source_run
row and a "metric unavailable" line in the recap.
"""
from __future__ import annotations


class ConfigError(RuntimeError):
    """A required env var or config value is missing."""


class SourceError(RuntimeError):
    """A source system pull failed or returned something we refuse to trust."""

    def __init__(self, source: str, message: str) -> None:
        self.detail = f"{source}: {message}"
        super().__init__(self.detail)
        self.source = source
        self.message = message
