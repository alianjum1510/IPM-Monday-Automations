"""
Verifies the two tokens monday signs for this app.

verify_monday_request - the JWT monday sends with every Automation Block call.
verify_session_token  - the session token a View feature's page sends with its
                        own API calls (see the end of this module).

verify_monday_request: one dependency for every block route. A request passes only when:

  signature  HS256, signed with the app's Signing Secret (MONDAY_SIGNING_SECRET)    else 401
  exp        present and not in the past (CLOCK_SKEW_SECONDS allowed)               else 401
  aud        one of MONDAY_JWT_AUDIENCE_BASE_URLS + the path this request came in on  else 401

monday sets `aud` to the endpoint it called, so a token for one block's route is
not accepted on another's. The exact `aud` format is measured on a draft before
it is enforced: with MONDAY_JWT_AUDIENCE_MODE=report an `aud` mismatch is logged
and let through (signature and exp are still enforced). `enforce` is the default
and the only mode for production.

API calls use MONDAY_API_TOKEN, not the token's shortLivedToken. The token and
shortLivedToken are never logged; the request log gets aud, exp, iat and accountId.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

import jwt
from fastapi import Header, HTTPException, Request

from .blocks import MondayBlockError
from .config import get_secret, setting
from .views import ViewError

log = logging.getLogger("monday_apps.security")

CLOCK_SKEW_SECONDS = 30
AUDIENCE_MODES = ("enforce", "report")
LOGGED_CLAIMS = ("aud", "exp", "iat", "accountId")

# Every setting this check reads, loaded at startup for every feature.
SETTINGS = ("MONDAY_SIGNING_SECRET", "MONDAY_JWT_AUDIENCE_BASE_URLS", "MONDAY_JWT_AUDIENCE_MODE")


def required_settings() -> dict[str, tuple[str, ...]]:
    """The settings every feature route needs for this check, in the current mode."""
    required = {"MONDAY_SIGNING_SECRET": ("MONDAY_SIGNING_SECRET",)}
    if audience_mode() == "enforce":
        required["MONDAY_JWT_AUDIENCE_BASE_URLS"] = ("MONDAY_JWT_AUDIENCE_BASE_URLS",)
    return required


def audience_mode() -> str:
    # Optional, so read from what startup loaded - no monday-code lookup per request.
    mode = setting("MONDAY_JWT_AUDIENCE_MODE").strip().lower() or "enforce"
    if mode not in AUDIENCE_MODES:
        log.warning("MONDAY_JWT_AUDIENCE_MODE=%r is not one of %s - enforcing", mode, ", ".join(AUDIENCE_MODES))
        return "enforce"
    return mode


async def audience_base_urls() -> list[str]:
    raw = await get_secret("MONDAY_JWT_AUDIENCE_BASE_URLS")
    return [url.strip() for url in raw.split(",") if url.strip()]


def normalise_url(url: str) -> str:
    """Scheme and host lower-cased; query, fragment and trailing slash dropped."""
    parts = urlsplit(str(url).strip())
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def expected_audiences(base_urls: list[str], path: str) -> list[str]:
    """Each base URL plus the request path: "https://x.monday.app" + "/customer-name-split"."""
    return [normalise_url(base.rstrip("/") + "/" + path.lstrip("/")) for base in base_urls]


def audience_matches(aud, expected: list[str]) -> bool:
    auds = aud if isinstance(aud, list) else [aud]
    return any(isinstance(a, str) and normalise_url(a) in expected for a in auds)


async def verify_monday_request(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: the call came from monday, for this route. Returns the token's claims."""
    signing_secret = await get_secret("MONDAY_SIGNING_SECRET")
    if not signing_secret:
        log.error("MONDAY_SIGNING_SECRET is not set")
        raise MondayBlockError("Server misconfigured", "MONDAY_SIGNING_SECRET is not set on the app.")
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(
            token,
            signing_secret,
            algorithms=["HS256"],
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp"], "verify_aud": False},  # aud is checked below, per route
        )
    except jwt.PyJWTError as exc:
        log.warning("JWT verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    request.state.monday_claims = {key: claims[key] for key in LOGGED_CLAIMS if key in claims}

    path = request.url.path
    mode = audience_mode()
    base_urls = await audience_base_urls()
    if not base_urls and mode == "enforce":
        log.error("MONDAY_JWT_AUDIENCE_BASE_URLS is not set - cannot check the token audience")
        raise MondayBlockError("Server misconfigured", "MONDAY_JWT_AUDIENCE_BASE_URLS is not set on the app.")

    expected = expected_audiences(base_urls, path)
    if audience_matches(claims.get("aud"), expected):
        request.state.monday_aud_check = "ok"
        return claims

    details = {"aud": claims.get("aud"), "expected": expected, "path": path, "mode": mode}
    if mode == "report":
        request.state.monday_aud_check = "mismatch (report mode)"
        log.warning("JWT audience not matched (report mode, let through): aud=%s path=%s",
                    claims.get("aud"), path, extra={"payload": details})
        return claims

    request.state.monday_aud_check = "rejected"
    log.warning("JWT audience rejected: aud=%s path=%s", claims.get("aud"), path, extra={"payload": details})
    raise HTTPException(status_code=401, detail="Invalid token audience")


# ---------- View features: monday's session token ----------
#
# A View feature's page (item view, board view, widget) gets a session token
# from monday (monday.get('sessionToken')) and sends it as the Authorization
# header of every call to its own API. monday signs it HS256 with the app's
# Client Secret - not the Signing Secret the blocks' JWT uses - and puts the
# app, account and user under `dat`. A request passes only when:
#
#   signature  HS256, signed with MONDAY_CLIENT_SECRET          else 401
#   exp        not in the past, when present                    else 401
#   dat.app_id this app (MONDAY_APP_ID), when present           else 403
#
# Failures answer the page's {"error": ...} format (app/core/views.py).

DEFAULT_APP_ID = "11727119"  # Company Management

# Every setting this check reads, loaded at startup for every View feature.
SESSION_SETTINGS = ("MONDAY_CLIENT_SECRET", "MONDAY_APP_ID")
SESSION_REQUIRED_SETTINGS = {"MONDAY_CLIENT_SECRET": ("MONDAY_CLIENT_SECRET",)}


async def verify_session_token(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: the call came from this app's page inside monday. Returns the token's claims."""
    token = (authorization or "").strip()
    if token[:7].lower() == "bearer ":
        token = token[7:].strip()
    if token.count(".") != 2:
        raise ViewError(401, "Missing monday session token. Open this page inside monday.")

    client_secret = await get_secret("MONDAY_CLIENT_SECRET")
    if not client_secret:
        log.error("MONDAY_CLIENT_SECRET is not set - session tokens cannot be checked")
        raise ViewError(500, "MONDAY_CLIENT_SECRET is not set (Developer Center → Server-side code → Secrets).")

    try:
        claims = jwt.decode(
            token,
            client_secret,
            algorithms=["HS256"],
            options={"verify_aud": False, "verify_iat": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ViewError(401, "monday session expired. Reload the page.") from exc
    except jwt.PyJWTError as exc:
        log.warning("Session token verification failed: %s", exc)
        raise ViewError(401, "Invalid monday session token. Reload the page.") from exc

    dat = claims.get("dat") if isinstance(claims.get("dat"), dict) else {}
    request.state.monday_claims = {
        key: value for key, value in (
            ("user_id", dat.get("user_id")),
            ("account_id", dat.get("account_id")),
            ("app_id", dat.get("app_id")),
            ("exp", claims.get("exp")),
        ) if value is not None
    }

    app_id = dat.get("app_id")
    if app_id not in (None, "") and str(app_id) != (setting("MONDAY_APP_ID") or DEFAULT_APP_ID):
        log.warning("Session token for app %s rejected", app_id)
        raise ViewError(403, "This session belongs to another app.")
    return claims
