"""
Picks the processor for the board the automation ran on:
  KUNDEN_BOARD_IDS  -> kunden.run     full name -> Teil 1 + Teil 2 (was Kunden-board-customer-name-split)
  any other board   -> warm_lead.run  Customer Name cut, overflow -> Customer Name 2 (was customer_name_split_py,
                                      which ran on any board, e.g. Warm Lead Mining Board (Copy) 5106281544)

The board id only picks the processor INSIDE this feature; which feature runs
is decided by the route the block called.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from fastapi.responses import JSONResponse

from .processors import kunden, warm_lead

Flow = Callable[[dict, int, int], Awaitable["dict | JSONResponse"]]

DEFAULT_BOARD_ID = 5100825258  # the old app's DEFAULT_BOARD_ID, a Warm Lead board

KUNDEN_BOARD_IDS = {
    5099245948,  # S.B Leads' Kunden (customers) [Dev], workspace Netgains Dev Sandbox
    5094068289,  # Sandbox Kunden (customers)
}


def flow_for(board_id: int) -> Flow:
    if board_id in KUNDEN_BOARD_IDS:
        return kunden.run
    return warm_lead.run


async def split_item(fields: dict, board_id: int, item_id: int) -> dict | JSONResponse:
    return await flow_for(board_id)(fields, board_id, item_id)
