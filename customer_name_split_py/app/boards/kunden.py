"""
SP Leads Kunden Customer Dev and Sandbox boards (was the Kunden-board-customer-name-split app).

The full name (Kundenname (voll), the item name) is split into
Kundenname (Teil 1), at most MAX_NAME_LENGTH characters, and Kundenname (Teil 2),
the overflow. The full name itself is never changed.

The column ids are the same on both boards.
"""

from __future__ import annotations

import logging

from fastapi.responses import JSONResponse

from ..block import OK, monday_error
from ..config import settings
from ..monday import ColumnValue, read_columns, write_parts
from ..split import split_customer_name

log = logging.getLogger("customer_name_split")

SOURCE_COLUMN_ID = "name"  # Kundenname (voll), the item name. Read only
PART1_COLUMN_ID = "text_mkt92ar9"  # Kundenname (Teil 1)
PART2_COLUMN_ID = "text_mksb1npw"  # Kundenname (Teil 2)


def _payload(board_id: int, item_id: int, **fields) -> dict:
    """The log line's payload on the Developer Center's Logs page."""
    return {"payload": {"flow": "kunden", "board_id": str(board_id), "item_id": str(item_id), **fields}}


async def run(fields: dict, board_id: int, item_id: int) -> dict | JSONResponse:
    try:
        source, part1, part2 = await read_columns(item_id, SOURCE_COLUMN_ID, PART1_COLUMN_ID, PART2_COLUMN_ID)
        result = split_customer_name(source.text, max_length=settings.max_name_length)

        # Only write what differs, so a re-run (or a trigger fired by our own write) is a no-op.
        changes = [
            ColumnValue(col.id, col.type, value)
            for col, value in ((part1, result.part1), (part2, result.part2))
            if col.text != value
        ]
        if not changes:
            log.info(
                "[kunden item %s] %d chars - Teil 1 and Teil 2 already up to date",
                item_id, len(source.text),
                extra=_payload(board_id, item_id, chars=len(source.text), updated=[]),
            )
            return OK

        if settings.teil2_max_length and len(result.part2) > settings.teil2_max_length:
            log.warning(
                "[item %s] Teil 2 is %d chars, over the %d limit",
                item_id, len(result.part2), settings.teil2_max_length,
                extra=_payload(board_id, item_id, teil2_chars=len(result.part2)),
            )

        await write_parts(board_id, item_id, changes)

        log.info(
            "[kunden item %s] %d chars -> Teil 1 %d + Teil 2 %d (updated: %s)",
            item_id, len(source.text), len(result.part1), len(result.part2),
            ", ".join(c.id for c in changes),
            extra=_payload(
                board_id, item_id,
                chars=len(source.text), was_split=result.was_split,
                teil1_chars=len(result.part1), teil2_chars=len(result.part2),
                updated=[c.id for c in changes],
            ),
        )
        return OK
    except Exception as exc:  # noqa: BLE001 - surface any failure to monday's activity log
        log.exception("[kunden item %s] split failed", item_id, extra=_payload(board_id, item_id, error=str(exc)))
        return monday_error("Name split failed", str(exc))
