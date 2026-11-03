"""
address_validator: monday.com Automation Blocks (action) on the Address Master
boards. Each block calls its own route and the route fixes the mode, since a
block's payload does not say which column changed:

  POST /address-validator/fill       "Fill address from full address for {Item Id} on {Board Id}"
                                     mode "address" - When Vollständige Adresse changes
  POST /address-validator/validate   "Validate address for {Item Id} on {Board Id}"
                                     mode "fields"  - When Adresszeile 1 / Postcode changes
  POST /address-validator            auto - the old app's /action, kept so it still works

Block input fields (Developer Center):
  boardId  required
  itemId   required (main field)
"""

from __future__ import annotations

import logging

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool

from app.core.blocks import OK, monday_error
from app.core.config import get_secret
from app.core.features import Feature, feature_router
from app.core.security import verify_monday_request

from . import payload, service
from .boards import SETTINGS as BOARD_SETTINGS
from .schemas import BlockOutput, MondayError

log = logging.getLogger("address_validator")

NAME = "address_validator"

router = feature_router(NAME, service.REQUIRED_SETTINGS)
RESPONSES = {400: {"model": MondayError}}


async def run(request: Request, mode: str | None, claims: dict):
    try:
        body = await request.json()
    except ValueError:
        return monday_error("Malformed request", "The request body is not valid JSON.")
    if not isinstance(body, dict):
        return monday_error("Malformed request", "The request body is not a JSON object.")

    token = payload.get_token(await get_secret("MONDAY_API_TOKEN", "MONDAY_API_KEY"), claims)
    try:
        result = await run_in_threadpool(service.action, body, mode, token)
    except Exception as exc:  # noqa: BLE001 - surface any failure to monday's activity log
        item_id = payload.extract_ids_from_payload(payload.normalize_action_payload(body))["itemId"]
        log.exception(
            "[address item %s] validation failed", item_id,
            extra={"payload": {"item_id": item_id, "mode": mode or "auto", "error": str(exc)}},
        )
        return monday_error("Address validation failed", str(exc))

    if not result.get("success"):
        return monday_error("Missing input", result["reason"])
    if result.get("skipped"):
        log.info("skipped: %s", result["reason"], extra={"payload": {"mode": mode or "auto", "reason": result["reason"]}})
    return OK


# claims: the same verify_monday_request the router runs - FastAPI runs it once per request.

@router.post("/address-validator/fill", response_model=BlockOutput, responses=RESPONSES)
@router.post("/address-validator/fill/", response_model=BlockOutput, include_in_schema=False)
async def fill_address(request: Request, claims: dict = Depends(verify_monday_request)):
    return await run(request, "address", claims)


@router.post("/address-validator/validate", response_model=BlockOutput, responses=RESPONSES)
@router.post("/address-validator/validate/", response_model=BlockOutput, include_in_schema=False)
async def validate_address(request: Request, claims: dict = Depends(verify_monday_request)):
    return await run(request, "fields", claims)


@router.post("/address-validator", response_model=BlockOutput, responses=RESPONSES)
@router.post("/address-validator/", response_model=BlockOutput, include_in_schema=False)
async def auto_address(request: Request, claims: dict = Depends(verify_monday_request)):
    return await run(request, None, claims)


FEATURE = Feature(
    name=NAME,
    router=router,
    required_settings=service.REQUIRED_SETTINGS,
    optional_settings=("MONDAY_API_TOKEN", "MONDAY_API_KEY", *BOARD_SETTINGS),
)
