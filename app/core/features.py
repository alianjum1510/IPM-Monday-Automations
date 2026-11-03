"""
What a feature is, and the dependencies every feature router runs.

A feature module (app/features/<name>/router.py) builds its router and exposes
a Feature; app/api/router.py lists the Features. Nothing here knows any
individual feature. Two kinds:

  Automation Block   feature_router()          monday POSTs to it; every route checks the block JWT
  View (item view,   view_router() + view_api() a page monday shows in an iframe: the page is public,
  board view, widget)                           its API routes check monday's session token
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Request

from .blocks import MondayBlockError
from .config import check_required
from .logging import set_feature
from .security import verify_monday_request, verify_session_token
from .views import ViewError


@dataclass(frozen=True)
class Feature:
    name: str
    router: APIRouter
    # key -> the names it may be set under, e.g. {"MONDAY_API_TOKEN": ("MONDAY_API_TOKEN", "MONDAY_API_KEY")}
    required_settings: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Optional keys the feature reads, loaded at startup so synchronous code sees them.
    optional_settings: tuple[str, ...] = ()
    # Which monday token its routes check: "block" (verify_monday_request) or "session" (verify_session_token).
    auth: str = "block"

    def setting_keys(self) -> list[str]:
        names = [name for names in self.required_settings.values() for name in names]
        return [*names, *self.optional_settings]


def feature_router(name: str, required_settings: dict[str, tuple[str, ...]]) -> APIRouter:
    """
    A router whose every route, in order:
      1. tags the request and its log lines with the feature name
      2. verifies the monday JWT (signature, exp, aud for this route)
      3. answers monday's error format if a setting the feature needs is missing
    """

    async def require_settings() -> None:
        missing = await check_required(required_settings)
        if missing:
            raise MondayBlockError(
                "Server misconfigured", f"{name}: missing setting(s) {', '.join(missing)} on the app."
            )

    return APIRouter(dependencies=[Depends(tag(name)), Depends(verify_monday_request), Depends(require_settings)])


def view_router(name: str) -> APIRouter:
    """
    A View feature's router: every route tags the request and its log lines with
    the feature name, and nothing more - monday's iframe loads the page and its
    assets with no token. Each API route adds dependencies=view_api(...).
    """
    return APIRouter(dependencies=[Depends(tag(name))])


def view_api(name: str, required_settings: dict[str, tuple[str, ...]]) -> list:
    """
    The dependencies of a View feature's API route, in order:
      1. verifies monday's session token (signature, exp, app id)
      2. answers {"error": ...} if a setting the feature needs is missing
    """

    async def require_settings() -> None:
        missing = await check_required(required_settings)
        if missing:
            raise ViewError(500, f"{name}: missing setting(s) {', '.join(missing)} on the app.")

    return [Depends(verify_session_token), Depends(require_settings)]


def tag(name: str):
    """The dependency that tags a request and its log lines with the feature that answers it."""

    async def tag_feature(request: Request) -> None:
        # async: runs in the request's own task, so the log context reaches the route.
        request.state.feature = name
        set_feature(name)

    return tag_feature
