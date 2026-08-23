"""Env config. Every secret comes from the environment, never the repo."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

DEFAULT_TIMEZONE = "America/New_York"

# Claude model used for recap generation. Overridable per deployment.
RECAP_MODEL = os.getenv("RECAP_MODEL", "claude-opus-5")


def timezone_name() -> str:
    return os.getenv("TIMEZONE") or DEFAULT_TIMEZONE


def get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def require(name: str) -> str:
    value = get(name)
    if value is None:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def get_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = get(name)
    if raw is None:
        return list(default or [])
    return [part.strip() for part in raw.split(",") if part.strip()]
