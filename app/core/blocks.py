"""What an Automation Block action receives from monday, and the error format monday shows."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

OK = {"outputFields": {}}


def field(fields: dict, key: str):
    """Field value, unwrapping the object form some block field types use ({"value": ...})."""
    value = fields.get(key)
    if isinstance(value, dict):
        value = next((value[k] for k in ("value", "id", key) if value.get(k) not in (None, "")), None)
    return None if value in (None, "") else value


def monday_error(title: str, description: str) -> JSONResponse:
    """
    monday's error format, so the failure shows in the automation's activity log.
    severityCode 4000 fails the run; a 4xx is not retried by monday.
    """
    return JSONResponse(
        status_code=400,
        content={
            "severityCode": 4000,
            "notificationErrorTitle": title,
            "notificationErrorDescription": description,
            "runtimeErrorDescription": description,
        },
    )


class MondayBlockError(Exception):
    """Raised from a dependency to answer with monday_error() - e.g. a setting the app is missing."""

    def __init__(self, title: str, description: str):
        super().__init__(description)
        self.title = title
        self.description = description


async def monday_block_error_handler(_: Request, exc: MondayBlockError) -> JSONResponse:
    return monday_error(exc.title, exc.description)
