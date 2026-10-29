"""
Thin async client for the monday GraphQL calls the name-split features need:
column lookup, read and write. Company Enrichment keeps its own client
(company_enrichment/services/monday.py), which retries rejected columns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .config import get_secret, setting

API_URL = "https://api.monday.com/v2"


def api_version() -> str:
    return setting("MONDAY_API_VERSION") or "2025-04"


class MondayApiError(Exception):
    pass


@dataclass(frozen=True)
class ColumnValue:
    id: str
    type: str
    text: str


async def _gql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    api_token = await get_secret("MONDAY_API_TOKEN", "MONDAY_API_KEY")
    if not api_token:
        raise MondayApiError("MONDAY_API_TOKEN is not set")
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            API_URL,
            json={"query": query, "variables": variables},
            headers={
                "Authorization": api_token,
                "API-Version": api_version(),
                "Content-Type": "application/json",
            },
        )
    body = res.json()
    if res.status_code >= 400 or body.get("errors") or body.get("error_message"):
        detail = body.get("errors") or body.get("error_message")
        raise MondayApiError(f"monday API error ({res.status_code}): {json.dumps(detail)}")
    return body["data"]


async def find_column_id(board_id: int, titles: list[str]) -> str | None:
    """
    Id of the first board column whose title matches one of `titles` (case-insensitive),
    trying them in order. Lets one deployment serve boards whose column ids differ.
    """
    data = await _gql(
        """
        query ($boardId: [ID!]) {
          boards(ids: $boardId) { columns { id title type } }
        }
        """,
        {"boardId": [board_id]},
    )
    boards = data.get("boards") or []
    if not boards:
        raise MondayApiError(f"Board {board_id} not found")
    by_title = {c["title"].strip().casefold(): c["id"] for c in boards[0]["columns"]}
    for title in titles:
        if (col_id := by_title.get(title.strip().casefold())):
            return col_id
    return None


async def read_columns(item_id: int, *column_ids: str) -> list[ColumnValue]:
    """Reads the current text and type of the given columns in one call. "name" is the item name."""
    col_ids = [c for c in column_ids if c != "name"]
    data = await _gql(
        """
        query ($itemId: [ID!], $colIds: [String!]) {
          items(ids: $itemId) {
            name
            column_values(ids: $colIds) { id type text }
          }
        }
        """,
        {"itemId": [item_id], "colIds": col_ids},
    )

    items = data.get("items") or []
    if not items:
        raise MondayApiError(f"Item {item_id} not found")
    item = items[0]

    def get(col_id: str) -> ColumnValue:
        if col_id == "name":
            return ColumnValue("name", "name", item["name"] or "")
        for cv in item["column_values"]:
            if cv["id"] == col_id:
                return ColumnValue(cv["id"], cv["type"], cv["text"] or "")
        raise MondayApiError(f'Column "{col_id}" not found on item {item_id}')

    return [get(c) for c in column_ids]


def _value_for(col_type: str, text: str) -> Any:
    if col_type in ("name", "text"):
        return text
    if col_type == "long_text":
        return {"text": text}
    raise MondayApiError(
        f'Unsupported column type "{col_type}". Use a Text, Long Text or the Name column.'
    )


async def write_parts(
    board_id: int, item_id: int, cols: list[ColumnValue]
) -> None:
    """Writes the parts in a single mutation so the item never sits half updated."""
    values = {c.id: _value_for(c.type, c.text) for c in cols}
    await _gql(
        """
        mutation ($boardId: ID!, $itemId: ID!, $values: JSON!) {
          change_multiple_column_values(board_id: $boardId, item_id: $itemId, column_values: $values) { id }
        }
        """,
        {"boardId": board_id, "itemId": item_id, "values": json.dumps(values, ensure_ascii=False)},
    )
