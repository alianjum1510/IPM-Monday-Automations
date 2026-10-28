import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.testing import TEST_SIGNING_SECRET, monday_auth
from app.features.customer_name_split import monday
from app.features.customer_name_split.router import FEATURE
from main import create_app

KUNDEN_DEV_BOARD = 5099245948
KUNDEN_SANDBOX_BOARD = 5094068289
WARM_LEAD_BOARD = 5106281544
WARM_LEAD_OLD_DEFAULT_BOARD = 5100825258

LONG_NAME = (
    "Zweckverband Gemeinschaftliche Wasserversorgung und Abwasserentsorgung "
    "Landkreis Oberallgäu Süd Kempten Immenstadt"
)
PART1 = "Zweckverband Gemeinschaftliche Wasserversorgung und Abwasserentsorgung Landkreis Oberallgäu Süd"
PART2 = "Kempten Immenstadt"

PATH = "/customer-name-split"
LEGACY_PATH = "/monday/split-name"

# This feature alone, as the deployment serves it: proves it needs no other feature.
client = TestClient(create_app([FEATURE]))


def auth(path: str = PATH, secret: str = TEST_SIGNING_SECRET) -> dict:
    """A monday JWT for `path` (its aud names the route it is sent to)."""
    return monday_auth(path, secret=secret)


def body(board_id, item_id=42, **extra) -> dict:
    return {"payload": {"inputFields": {"boardId": board_id, "itemId": item_id, **extra}}}


@pytest.fixture
def fake_monday(monkeypatch):
    """
    Replaces the monday API with one in-memory item that has both boards' columns,
    and records mutations.
    """
    state = {
        "name": LONG_NAME,
        "text_mkt92ar9": "", "text_mksb1npw": "",  # Kunden: Teil 1, Teil 2
        "text_cust": LONG_NAME, "text_mm7qvqph": "",  # Warm Lead: Customer Name, Customer Name 2
        "columns": [
            {"id": "name", "title": "Name", "type": "name"},
            {"id": "text_cust", "title": "Company / Customer Name", "type": "text"},
            {"id": "text_mm7qvqph", "title": "Company / Customer Name 2", "type": "text"},
        ],
        "mutations": [], "calls": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        assert request.headers["Authorization"] == "test-api-token"
        payload = json.loads(request.content)
        if "mutation" in payload["query"]:
            values = json.loads(payload["variables"]["values"])
            state["mutations"].append(values)
            state.update(values)
            return httpx.Response(200, json={"data": {"change_multiple_column_values": {"id": "42"}}})
        if "boards(" in payload["query"]:
            return httpx.Response(200, json={"data": {"boards": [{"columns": state["columns"]}]}})
        cols = [
            {"id": c, "type": "text", "text": state[c]}
            for c in payload["variables"]["colIds"] if c in state
        ]
        return httpx.Response(200, json={"data": {"items": [{"name": state["name"], "column_values": cols}]}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        monday.httpx, "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    return state
