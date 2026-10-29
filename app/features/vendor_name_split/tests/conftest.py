import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import monday_client
from app.core.testing import TEST_SIGNING_SECRET, monday_auth
from app.features.vendor_name_split.router import FEATURE
from main import create_app

VENDORS_BOARD = 5094193564
PATH = "/vendor-name-split"

LONG_NAME = (
    "Bayerische Maschinenbau und Anlagentechnik Aktiengesellschaft Zweigniederlassung "
    "München Nord Entwicklungszentrum Garching"
)
PART1 = "Bayerische Maschinenbau und Anlagentechnik Aktiengesellschaft Zweigniederlassung München Nord"
PART2 = "Entwicklungszentrum Garching"

# This feature alone, as the deployment serves it: proves it needs no other feature.
client = TestClient(create_app([FEATURE]))


def auth(path: str = PATH, secret: str = TEST_SIGNING_SECRET) -> dict:
    """A monday JWT for `path` (its aud names the route it is sent to)."""
    return monday_auth(path, secret=secret)


def body(board_id=VENDORS_BOARD, item_id=42) -> dict:
    return {"payload": {"inputFields": {"boardId": board_id, "itemId": item_id}}}


@pytest.fixture
def fake_monday(monkeypatch):
    """The monday API as one in-memory Vendors item; records mutations."""
    state = {"name": LONG_NAME, "text_mkt92ar9": "", "text_mksb1npw": "", "mutations": [], "calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        assert request.headers["Authorization"] == "test-api-token"
        payload = json.loads(request.content)
        if "mutation" in payload["query"]:
            assert payload["variables"]["boardId"] == VENDORS_BOARD
            values = json.loads(payload["variables"]["values"])
            state["mutations"].append(values)
            state.update(values)
            return httpx.Response(200, json={"data": {"change_multiple_column_values": {"id": "42"}}})
        cols = [
            {"id": c, "type": "text", "text": state[c]}
            for c in payload["variables"]["colIds"] if c in state
        ]
        return httpx.Response(200, json={"data": {"items": [{"name": state["name"], "column_values": cols}]}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        monday_client.httpx, "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    return state
