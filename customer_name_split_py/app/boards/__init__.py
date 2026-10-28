"""
Picks the flow for the board the automation ran on:
  KUNDEN_BOARD_IDS  -> kunden.run     full name -> Teil 1 + Teil 2 (was Kunden-board-customer-name-split)
  any other board   -> warm_lead.run  Customer Name cut, overflow -> Customer Name 2 (was customer_name_split_py,
                                      which ran on any board, e.g. Warm Lead Mining Board (Copy) 5106281544)
"""

from __future__ import annotations

from typing import Awaitable, Callable

from fastapi.responses import JSONResponse

from . import kunden, warm_lead

Flow = Callable[[dict, int, int], Awaitable["dict | JSONResponse"]]

KUNDEN_BOARD_IDS = {
    5099245948,  # S.B Leads' Kunden (customers) [Dev], workspace Netgains Dev Sandbox
    5094068289,  # Sandbox Kunden (customers)
}


def flow_for(board_id: int) -> Flow:
    if board_id in KUNDEN_BOARD_IDS:
        return kunden.run
    return warm_lead.run
