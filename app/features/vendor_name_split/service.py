"""
Vendors board (5094193564): the vendor name (the item name) is split into
Vendor Name Part 1, at most MAX_NAME_LENGTH characters cut at a word, and
Vendor Name Part 2, the rest. The vendor name itself is never changed.

A name that fits goes whole into Part 1 and empties Part 2, so shortening a
vendor's name clears the old overflow.
"""

from __future__ import annotations

import logging

from fastapi.responses import JSONResponse

from app.core.blocks import OK, monday_error
from app.core.config import setting
from app.core.monday_client import ColumnValue, read_columns, write_parts
from app.core.name_split import split_customer_name

log = logging.getLogger("vendor_name_split")

SOURCE_COLUMN_ID = "name"  # Vendors, the item name. Read only
PART1_COLUMN_ID = "text_mkt92ar9"  # Vendor Name Part 1
PART2_COLUMN_ID = "text_mksb1npw"  # Vendor Name Part 2

# key -> accepted names. MONDAY_SIGNING_SECRET is checked by app/core/security.py for every feature.
REQUIRED_SETTINGS = {
    "MONDAY_API_TOKEN": ("MONDAY_API_TOKEN", "MONDAY_API_KEY"),
}


def max_name_length() -> int:
    """MAX_NAME_LENGTH, the same limit the other name splits use."""
    try:
        return int(setting("MAX_NAME_LENGTH") or 100)
    except ValueError:
        return 100


def _payload(board_id: int, item_id: int, **fields) -> dict:
    """The log line's payload on the Developer Center's Logs page."""
    return {"payload": {"board_id": str(board_id), "item_id": str(item_id), **fields}}


async def split_vendor_name(board_id: int, item_id: int) -> dict | JSONResponse:
    try:
        source, part1, part2 = await read_columns(item_id, SOURCE_COLUMN_ID, PART1_COLUMN_ID, PART2_COLUMN_ID)
        result = split_customer_name(source.text, max_length=max_name_length())

        # Only write what differs, so a re-run (or a trigger fired by our own write) is a no-op.
        changes = [
            ColumnValue(col.id, col.type, value)
            for col, value in ((part1, result.part1), (part2, result.part2))
            if col.text != value
        ]
        if not changes:
            log.info(
                "[vendor item %s] %d chars - Part 1 and Part 2 already up to date",
                item_id, len(source.text),
                extra=_payload(board_id, item_id, chars=len(source.text), updated=[]),
            )
            return OK

        await write_parts(board_id, item_id, changes)

        log.info(
            "[vendor item %s] %d chars -> Part 1 %d + Part 2 %d (updated: %s)",
            item_id, len(source.text), len(result.part1), len(result.part2),
            ", ".join(c.id for c in changes),
            extra=_payload(
                board_id, item_id,
                chars=len(source.text), was_split=result.was_split,
                part1_chars=len(result.part1), part2_chars=len(result.part2),
                updated=[c.id for c in changes],
            ),
        )
        return OK
    except Exception as exc:  # noqa: BLE001 - surface any failure to monday's activity log
        log.exception("[vendor item %s] split failed", item_id, extra=_payload(board_id, item_id, error=str(exc)))
        return monday_error("Vendor name split failed", str(exc))
