"""
A fake Address Master item and a fake HERE, both behind urllib.request.urlopen
(the feature's only way out), as in the old app's test/test_app.py.
"""
import copy
import json
import urllib.parse
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app.core.testing import TEST_SIGNING_SECRET, monday_auth
from app.features.address_validator import service
from app.features.address_validator.boards import boards
from app.features.address_validator.router import FEATURE
from main import create_app

BOARD_ID = "5090777446"  # Address Master Board (replica)
ORIGINAL_BOARD_ID = "5063711037"  # Address Master Board (original)
C = boards()[BOARD_ID]["columns"]

FILL = "/address-validator/fill"
VALIDATE = "/address-validator/validate"
AUTO = "/address-validator"

TOKEN = "test-api-token"  # MONDAY_API_TOKEN in app/conftest.py
LOCATION_ORIGINAL_BOARD = "location_original_board"  # ADDRESS_COLUMN_LOCATION_ID, set on monday for the original board

HERE_BORSIG = {
    "title": "Borsigstraße 15, 51381 Leverkusen, Deutschland",
    "resultType": "houseNumber",
    "houseNumberType": "PA",
    "address": {
        "label": "Borsigstraße 15, 51381 Leverkusen, Deutschland",
        "countryCode": "DEU", "countryName": "Deutschland",
        "state": "Nordrhein-Westfalen", "county": "Leverkusen", "city": "Leverkusen",
        "street": "Borsigstraße", "postalCode": "51381", "houseNumber": "15",
    },
    "position": {"lat": 51.0456789, "lng": 7.0123456},
    "scoring": {"queryScore": 1},
}

FULL = "Borsigstraße 15, 51381 Leverkusen, Deutschland"

# This feature alone, as the deployment serves it: proves it needs no other feature.
client = TestClient(create_app([FEATURE]))


def auth(path=FILL, secret=TEST_SIGNING_SECRET, **kwargs):
    """A monday JWT for `path` (its aud names the route it is sent to)."""
    return monday_auth(path, secret=secret, **kwargs)


class FakeResponse:
    def __init__(self, data, status=200):
        self.status = status
        self._body = json.dumps(data).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeBoard:
    """One monday item and HERE. Records mutations, HERE queries and the monday token used."""

    def __init__(self):
        self.item = None
        self.mutations = []
        self.here_queries = []
        self.monday_tokens = []

    def new_item(self, values, board_id=BOARD_ID):
        self.item = {
            "id": "111",
            "name": "Test",
            "board": {"id": board_id},
            "column_values": [{"id": cid, "text": values.get(cid, ""), "value": None, "type": "text"}
                              for cid in boards()[board_id]["columns"].values() if cid],
        }
        self.mutations = []
        self.here_queries = []
        service.recent_writes.clear()

    def text(self, cid):
        return next(c for c in self.item["column_values"] if c["id"] == cid)["text"]

    def set_text(self, cid, value):
        next(c for c in self.item["column_values"] if c["id"] == cid)["text"] = value

    def event(self, column_id, board_id=BOARD_ID):
        """A webhook-style payload that names the changed column."""
        return {"event": {"pulseId": int(self.item["id"]), "boardId": int(board_id), "columnId": column_id}}

    def block_payload(self, board_id=BOARD_ID):
        """monday action block (what the live app receives): only boardId + itemId, no
        column ID, so the mode comes from the route the block calls."""
        return {
            "payload": {
                "blockKind": "action",
                "inboundFieldValues": {"boardId": int(board_id), "itemId": int(self.item["id"])},
                "inputFields": {"boardId": int(board_id), "itemId": int(self.item["id"])},
                "recipeId": 1, "integrationId": 2,
            },
            "runtimeMetadata": {"actionUuid": "x"},
        }

    def urlopen(self, req, timeout=None):
        url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
        if url.startswith("https://geocode.search.hereapi.com"):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            q = params.get("q", [None])[0]
            self.here_queries.append({"q": q, "in": params.get("in", [None])[0],
                                      "apiKey": params.get("apiKey", [None])[0]})
            return FakeResponse({"items": [HERE_BORSIG] if "borsig" in q.lower() else []})
        if url == "https://api.monday.com/v2":
            self.monday_tokens.append(req.headers.get("Authorization"))
            body = json.loads(req.data.decode("utf-8"))
            if "change_multiple_column_values" in body["query"]:
                values = json.loads(body["variables"]["values"])
                self.mutations.append(values)
                for cid, v in values.items():
                    col = next(c for c in self.item["column_values"] if c["id"] == cid)
                    col["text"] = v if isinstance(v, str) else (v.get("label") or v.get("address") or "")
                return FakeResponse({"data": {"change_multiple_column_values": {"id": self.item["id"]}}})
            return FakeResponse({"data": {"items": [copy.deepcopy(self.item)] if self.item else []}})
        raise AssertionError(f"unexpected request {url}")


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setenv("ADDRESS_COLUMN_LOCATION_ID", LOCATION_ORIGINAL_BOARD)
    fake = FakeBoard()
    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    service.recent_writes.clear()
    yield fake
    service.recent_writes.clear()
