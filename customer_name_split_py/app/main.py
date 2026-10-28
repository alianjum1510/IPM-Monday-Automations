"""
customer_name_split: monday.com Automation Block (action) for:
  "Split Customer Name for {Item id} in {board id}"
added to e.g. "When an item is created" (form submissions create items).

One app for both board families; the board id picks the flow (see app/boards):
  KUNDEN_BOARD_IDS  S.B Leads' Kunden [Dev] / Sandbox Kunden -> Teil 1 + Teil 2
  any other board   e.g. Warm Lead Mining Board (Copy) -> Customer Name + Customer Name 2

Block input fields (Developer Center):
  itemId   required
  boardId  fallback: DEFAULT_BOARD_ID
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request

from .auth import monday_session
from .block import field, monday_error
from .boards import flow_for
from .config import assert_configured

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("customer_name_split")

DEFAULT_BOARD_ID = 5100825258  # the old app's DEFAULT_BOARD_ID, a Warm Lead board


@asynccontextmanager
async def lifespan(_: FastAPI):
    await assert_configured()
    yield


app = FastAPI(title="customer_name_split", lifespan=lifespan)


# HEAD too: monday's health checker (userAgent MondayHealth) uses it.
@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict:
    return {"ok": True}


# "/" so the bare monday-code Version URL works as the Execution URL, like the other apps.
@app.post("/", dependencies=[Depends(monday_session)])
@app.post("/monday/split-name", dependencies=[Depends(monday_session)])
async def split_name(request: Request):
    body = await request.json()
    payload = body.get("payload") or {}
    # Automation blocks (monday workflows) send `inputFields`; the legacy sentence builder `inboundFieldValues`.
    fields = payload.get("inputFields") or payload.get("inboundFieldValues") or {}
    log.info("input fields: %s", fields)

    try:
        board_id = int(field(fields, "boardId") or DEFAULT_BOARD_ID)
        item_id = int(field(fields, "itemId"))
    except (TypeError, ValueError):
        return monday_error("Missing input", f"Board and item are required. Got: {fields}")

    return await flow_for(board_id)(fields, board_id, item_id)
