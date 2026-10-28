"""
Warm Lead Mining Board copy (was the customer_name_split_py app).

Company / Customer Name over MAX_NAME_LENGTH characters is cut in place and the
overflow goes to Company / Customer Name 2.

Columns, first match wins:
  1. sourceColumnId / targetColumnId from the block (legacy recipe only)
  2. SOURCE_COLUMN_ID / TARGET_COLUMN_ID below
  3. board column whose title is in SOURCE_COLUMN_TITLES / TARGET_COLUMN_TITLES below
"""

from __future__ import annotations

import logging

from fastapi.responses import JSONResponse

from app.core.blocks import OK, field, monday_error

from ..monday import ColumnValue, MondayApiError, find_column_id, read_columns, write_parts
from ..settings import settings
from ..split import split_customer_name

log = logging.getLogger("customer_name_split")

SOURCE_COLUMN_ID = None  # found by title
SOURCE_COLUMN_TITLES = ["Company / Customer Name"]
TARGET_COLUMN_ID = "text_mm7qvqph"  # Company / Customer Name 2
TARGET_COLUMN_TITLES = ["Company / Customer Name 2"]


def _payload(board_id: int, item_id: int, **fields) -> dict:
    """The log line's payload on the Developer Center's Logs page."""
    return {"payload": {"flow": "warm_lead", "board_id": str(board_id), "item_id": str(item_id), **fields}}


async def _column_id(fields: dict, input_key: str, col_id: str | None, titles: list[str], board_id: int) -> str:
    """Column id from the block input, then the fixed id, then a title lookup on the board."""
    col_id = field(fields, input_key) or col_id
    if col_id:
        return str(col_id)
    col_id = await find_column_id(board_id, titles)
    if not col_id:
        raise MondayApiError(f"Board {board_id} has no column titled {' or '.join(titles)}")
    return col_id


async def run(fields: dict, board_id: int, item_id: int) -> dict | JSONResponse:
    try:
        source_id = await _column_id(fields, "sourceColumnId", SOURCE_COLUMN_ID, SOURCE_COLUMN_TITLES, board_id)
        target_id = await _column_id(fields, "targetColumnId", TARGET_COLUMN_ID, TARGET_COLUMN_TITLES, board_id)
    except Exception as exc:  # noqa: BLE001 - surface to monday's activity log
        log.exception("[warm lead item %s] column lookup failed", item_id, extra=_payload(board_id, item_id, error=str(exc)))
        return monday_error("Column not found", str(exc))

    if source_id == target_id:
        return monday_error(
            "Same column selected", "Customer Name and Customer Name 2 must be different columns."
        )

    try:
        source, target = await read_columns(item_id, source_id, target_id)
        result = split_customer_name(source.text, max_length=settings.max_name_length)

        # Short enough: nothing to do. This is also what stops the loop, because our own
        # write to the source column fires the trigger again with a value <= the limit.
        if not result.was_split:
            log.info(
                "[warm lead item %s] %d chars - no split needed",
                item_id, len(source.text),
                extra=_payload(board_id, item_id, chars=len(source.text), was_split=False),
            )
            return OK

        if target.text and target.text != result.part2:
            log.info(
                '[warm lead item %s] Name 2 "%s" replaced with overflow "%s"', item_id, target.text, result.part2,
                extra=_payload(board_id, item_id, previous_name2=target.text),
            )
        if settings.teil2_max_length and len(result.part2) > settings.teil2_max_length:
            log.warning(
                "[warm lead item %s] Name 2 is %d chars, over the %d limit",
                item_id, len(result.part2), settings.teil2_max_length,
                extra=_payload(board_id, item_id, name2_chars=len(result.part2)),
            )

        await write_parts(
            board_id,
            item_id,
            [
                ColumnValue(source.id, source.type, result.part1),
                ColumnValue(target.id, target.type, result.part2),
            ],
        )

        log.info(
            "[warm lead item %s] split %d chars into %d + %d",
            item_id, len(source.text), len(result.part1), len(result.part2),
            extra=_payload(
                board_id, item_id,
                chars=len(source.text), was_split=True,
                name_chars=len(result.part1), name2_chars=len(result.part2),
                updated=[source.id, target.id],
            ),
        )
        return OK
    except Exception as exc:  # noqa: BLE001 - surface any failure to monday's activity log
        log.exception("[warm lead item %s] split failed", item_id, extra=_payload(board_id, item_id, error=str(exc)))
        return monday_error("Name split failed", str(exc))
