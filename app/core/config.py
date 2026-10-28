"""
Settings for every feature, from one place.

A plain environment variable wins (local runs, Docker, tests). On monday-code,
the Developer Center's Secrets and Environment variables are not guaranteed to
be in os.environ; they are served by a local monday-code service and read
through its SDK. Values read from there are kept for the life of the process,
so a changed secret needs a redeploy.

  setting('OPENAI_MODEL')                                sync - env, then what was read at startup
  await get_secret('MONDAY_API_TOKEN', 'MONDAY_API_KEY') async - also asks monday-code for a missing key

At startup, load() reads every key the features declare, so the synchronous
setting() sees them too. Only key NAMES and where they came from are ever
logged, never their values.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("monday_apps.config")

# key -> value, read from the monday-code service.
_cache: dict[str, str] = {}


def setting(*keys: str, default: str = "") -> str:
    """The first of `keys` that has a value - process environment first, then monday-code - or `default`."""
    for key in keys:
        if os.environ.get(key):
            return os.environ[key]
    for key in keys:
        if _cache.get(key):
            return _cache[key]
    return default


def source(key: str) -> str | None:
    """Where a key's value comes from: "env", "monday-code" or None. For the startup log."""
    if os.environ.get(key):
        return "env"
    if _cache.get(key):
        return "monday-code"
    return None


async def get_secret(*keys: str) -> str:
    """Like setting(), but a key that is still missing is looked up on the monday-code service."""
    value = setting(*keys)
    if value:
        return value
    found = await _from_monday_code(list(keys))
    _cache.update(found)
    return setting(*keys)


async def load(keys) -> dict[str, str]:
    """
    Reads every key not in the process environment from monday-code, in one session.
    Returns {key: source} for the keys that have a value.
    """
    keys = list(dict.fromkeys(keys))
    missing = [key for key in keys if not setting(key)]
    if missing:
        _cache.update(await _from_monday_code(missing))
    return {key: source(key) for key in keys if source(key)}


async def check_required(required: dict[str, tuple[str, ...]]) -> list[str]:
    """The keys of `required` ({key: accepted names}) that have no value under any of their names."""
    return [key for key, names in required.items() if not await get_secret(*names)]


async def _from_monday_code(keys: list[str]) -> dict[str, str]:
    """Secrets first, then Environment variables. {} off monday-code (local runs, tests)."""
    try:
        import monday_code
        from monday_code.exceptions import NotFoundException
    except ImportError:
        return {}

    found: dict[str, str] = {}
    try:
        async with monday_code.ApiClient(monday_code.Configuration()) as client:
            readers = [
                monday_code.SecretsApi(client).get_secret,
                monday_code.EnvironmentVariablesApi(client).get_environment_variable,
            ]
            for key in keys:
                for read in readers:
                    try:
                        value = await read(key)
                    except NotFoundException:
                        continue
                    if value not in (None, ""):
                        found[key] = str(value)
                        break
    except Exception as exc:  # noqa: BLE001 - not on monday-code, or the service is down
        log.warning("monday-code settings not read (%s) - using the process environment only", exc)
    return found
