"""
The error format of a View feature (item view, board view, widget): a page in
monday's iframe that calls its own /api routes with fetch.

The page reads `error` from the JSON and shows it, so every failure - a bad
session token, a missing setting, a rejected input - answers
{"error": "<message>"} with its status. An Automation Block answers monday's
format instead (app/core/blocks.py).
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ViewError(Exception):
    """Raised anywhere in a View feature's request to answer {"error": message} with `status`."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def view_error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


async def view_error_handler(_: Request, exc: ViewError) -> JSONResponse:
    return view_error(exc.status, exc.message)
