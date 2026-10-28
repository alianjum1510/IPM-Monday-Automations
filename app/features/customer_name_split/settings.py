from __future__ import annotations

import os
from dataclasses import dataclass


def _opt_int(name: str) -> int | None:
    raw = os.getenv(name)
    return int(raw) if raw else None


@dataclass(frozen=True)
class Settings:
    max_name_length: int = int(os.getenv("MAX_NAME_LENGTH", "100"))
    teil2_max_length: int | None = _opt_int("TEIL2_MAX_LENGTH")
    api_version: str = os.getenv("MONDAY_API_VERSION", "2025-04")
    api_url: str = "https://api.monday.com/v2"


settings = Settings()

# key -> accepted names. MONDAY_SIGNING_SECRET is checked by app/core/security.py for every feature.
REQUIRED_SETTINGS = {
    "MONDAY_API_TOKEN": ("MONDAY_API_TOKEN", "MONDAY_API_KEY"),
}
