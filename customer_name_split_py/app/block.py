"""What an Automation Block action receives from monday, and the error format monday shows."""

from __future__ import annotations

from fastapi.responses import JSONResponse

OK = {"outputFields": {}}


def field(fields: dict, key: str):
    """Field value, unwrapping the object form some block field types use ({"value": ...})."""
    value = fields.get(key)
    if isinstance(value, dict):
        value = next((value[k] for k in ("value", "id", key) if value.get(k) not in (None, "")), None)
    return None if value in (None, "") else value


def monday_error(title: str, description: str) -> JSONResponse:
    """monday's error format, so the failure shows in the automation's activity log."""
    return JSONResponse(
        status_code=400,
        content={
            "severityCode": 4000,
            "notificationErrorTitle": title,
            "notificationErrorDescription": description,
            "runtimeErrorDescription": description,
        },
    )
