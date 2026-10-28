"""
customer_name_split: monday.com Automation Block (action) for:
  "Split Customer Name for {Item id} in {board id}"
added to e.g. "When an item is created" (form submissions create items).

  POST /customer-name-split   canonical (the block's sub-route)
  POST /monday/split-name     the old app's URL

One feature for both board families; the board id picks the processor (see service.py):
  KUNDEN_BOARD_IDS  S.B Leads' Kunden [Dev] / Sandbox Kunden -> Teil 1 + Teil 2
  any other board   e.g. Warm Lead Mining Board (Copy) -> Customer Name + Customer Name 2

Block input fields (Developer Center):
  itemId   required
  boardId  fallback: DEFAULT_BOARD_ID
"""

from __future__ import annotations

import logging

from fastapi import Request

from app.core.blocks import field, monday_error
from app.core.features import Feature, feature_router

from . import service
from .schemas import BlockOutput, MondayError
from .settings import REQUIRED_SETTINGS

log = logging.getLogger("customer_name_split")

NAME = "customer_name_split"

router = feature_router(NAME, REQUIRED_SETTINGS)
RESPONSES = {400: {"model": MondayError}}


@router.post("/customer-name-split", response_model=BlockOutput, responses=RESPONSES)
@router.post("/customer-name-split/", response_model=BlockOutput, include_in_schema=False)
@router.post("/monday/split-name", response_model=BlockOutput, responses=RESPONSES)
async def split_name(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return monday_error("Malformed request", "The request body is not valid JSON.")

    payload = body.get("payload") if isinstance(body, dict) else None
    payload = payload if isinstance(payload, dict) else {}
    # Automation blocks (monday workflows) send `inputFields`; the legacy sentence builder `inboundFieldValues`.
    fields = payload.get("inputFields") or payload.get("inboundFieldValues") or {}
    fields = fields if isinstance(fields, dict) else {}
    log.info("input fields: %s", fields, extra={"payload": {"input_fields": fields}})

    try:
        board_id = int(field(fields, "boardId") or service.DEFAULT_BOARD_ID)
        item_id = int(field(fields, "itemId"))
    except (TypeError, ValueError):
        return monday_error("Missing input", f"Board and item are required. Got: {fields}")

    return await service.split_item(fields, board_id, item_id)


FEATURE = Feature(
    name=NAME,
    router=router,
    required_settings=REQUIRED_SETTINGS,
    optional_settings=("MONDAY_API_VERSION", "MAX_NAME_LENGTH", "TEIL2_MAX_LENGTH"),
)
