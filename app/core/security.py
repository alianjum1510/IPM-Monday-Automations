"""
Verifies the JWT monday sends with every Automation Block call.

One dependency for every feature route. A request passes only when:

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
