"""
The whole deployment (main.app) with both features' work replaced by recorders,
so these tests check routing, auth and logging without touching monday or OpenAI.
"""
import threading

import pytest
from fastapi.testclient import TestClient

import main
from app.core.testing import monday_auth
from app.features.company_enrichment import service as enrichment_service
from app.features.customer_name_split import service as split_service
from app.features.vendor_name_split import service as vendor_service

ENRICHMENT_PATHS = ['/', '/company-enrichment', '/company-enrichment/']
SPLIT_PATHS = ['/customer-name-split', '/customer-name-split/', '/monday/split-name']
VENDOR_PATHS = ['/vendor-name-split', '/vendor-name-split/']
FEATURE_PATHS = [*ENRICHMENT_PATHS, *SPLIT_PATHS, *VENDOR_PATHS]

BOARD_ID = 5106281544  # Warm Lead Mining Board (Copy): both features run on it


def block_body(board_id=BOARD_ID, item_id=42, **extra):
    return {'payload': {'inputFields': {'boardId': board_id, 'itemId': item_id}, **extra}}


class Calls:
    """What each feature was asked to do."""

    def __init__(self):
        self.enrichment = []
        self.split = []
        self.vendor = []
        self.enrichment_started = threading.Event()


@pytest.fixture
def calls(monkeypatch):
    recorded = Calls()

    def fake_enrich_item(board_id, item_id):
        recorded.enrichment.append((board_id, item_id))
        recorded.enrichment_started.set()
        return {'success': True}

    async def fake_split_item(fields, board_id, item_id):
        recorded.split.append((board_id, item_id))
        return {'outputFields': {}}

    async def fake_split_vendor_name(board_id, item_id):
        recorded.vendor.append((board_id, item_id))
        return {'outputFields': {}}

    monkeypatch.setattr(enrichment_service, 'enrich_item', fake_enrich_item)
    monkeypatch.setattr(split_service, 'split_item', fake_split_item)
    monkeypatch.setattr(vendor_service, 'split_vendor_name', fake_split_vendor_name)
    return recorded


@pytest.fixture
def client():
    # `with` runs the startup (settings check) as monday-code does.
    with TestClient(main.app) as test_client:
        yield test_client


def post(client, path, json=None, auth_path=None, **auth_kwargs):
    """POST as monday does: a JWT whose aud is the route called (or `auth_path`)."""
    return client.post(path, json=block_body() if json is None else json,
                       headers=monday_auth(auth_path or path, **auth_kwargs))
