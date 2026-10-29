"""
vendor_name_split: monday.com Automation Block (action) for:
  "Vendor Name Split for {Item id} in {board id}"
on the Vendors board, added to "When an item is created" and "When item name changes".

  POST /vendor-name-split

Block input fields (Developer Center):
  itemId   required
  boardId  required
"""

from __future__ import annotations

import logging

from fastapi import Request

from app.core.blocks import field, monday_error
from app.core.features import Feature, feature_router

from . import service
from .schemas import BlockOutput, MondayError

log = logging.getLogger("vendor_name_split")

NAME = "vendor_name_split"

router = feature_router(NAME, service.REQUIRED_SETTINGS)
RESPONSES = {400: {"model": MondayError}}


@router.post("/vendor-name-split", response_model=BlockOutput, responses=RESPONSES)
@router.post("/vendor-name-split/", response_model=BlockOutput, include_in_schema=False)
async def split_vendor_name(request: Request):
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
        board_id = int(field(fields, "boardId"))
        item_id = int(field(fields, "itemId"))
    except (TypeError, ValueError):
        return monday_error("Missing input", f"Board and item are required. Got: {fields}")

    return await service.split_vendor_name(board_id, item_id)


FEATURE = Feature(
    name=NAME,
    router=router,
    required_settings=service.REQUIRED_SETTINGS,
    optional_settings=("MONDAY_API_VERSION", "MAX_NAME_LENGTH"),
)
