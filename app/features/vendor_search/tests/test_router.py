import pytest

from app.core.testing import monday_auth
from app.features.vendor_search import service

from .conftest import BOARD, PATH, REQUEST_ID, body, client


@pytest.fixture
def started(monkeypatch):
    runs = []
    monkeypatch.setattr(service, 'start', lambda board_id, item_id: runs.append((board_id, item_id)))
    return runs


@pytest.mark.parametrize('path', [PATH, PATH + '/'])
def test_the_block_acks_at_once_and_starts_the_search(started, path):
    res = client.post(path, json=body(), headers=monday_auth(path))
    assert res.status_code == 200
    assert res.json() == {'outputFields': {}}
    assert started == [(BOARD, REQUEST_ID)]


def test_the_legacy_field_name_is_accepted(started):
    legacy = {'payload': {'inboundFieldValues': {'boardId': str(BOARD), 'itemId': {'value': REQUEST_ID}}}}
    assert client.post(PATH, json=legacy, headers=monday_auth(PATH)).status_code == 200
    assert started == [(BOARD, REQUEST_ID)]


@pytest.mark.parametrize('payload', [
    {'payload': {'inputFields': {'boardId': BOARD}}},
    {'payload': {'inputFields': {'itemId': 'abc', 'boardId': BOARD}}},
    {'payload': 'x'},
    [],
])
def test_missing_ids_are_a_monday_error(started, payload):
    res = client.post(PATH, json=payload, headers=monday_auth(PATH))
    assert res.status_code == 400
    assert res.json()['severityCode'] == 4000
    assert started == []


def test_a_body_that_is_not_json_is_a_monday_error(started):
    res = client.post(PATH, content=b'{not json', headers={**monday_auth(PATH), 'Content-Type': 'application/json'})
    assert res.status_code == 400
    assert res.json()['notificationErrorTitle'] == 'Malformed request'
    assert started == []


def test_no_token_is_401(started):
    assert client.post(PATH, json=body()).status_code == 401
    assert started == []


def test_a_wrong_signature_is_401(started):
    res = client.post(PATH, json=body(), headers=monday_auth(PATH, secret='not-the-signing-secret-0123456789'))
    assert res.status_code == 401
    assert started == []


def test_a_token_for_another_route_is_401(started):
    res = client.post(PATH, json=body(), headers=monday_auth('/company-enrichment'))
    assert res.status_code == 401
    assert started == []


def test_without_the_openai_key_the_block_answers_a_monday_error(started, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY')
    res = client.post(PATH, json=body(), headers=monday_auth(PATH))
    assert res.status_code == 400
    assert 'OPENAI_API_KEY' in res.json()['notificationErrorDescription']
    assert started == []


def test_the_route_runs_the_search_in_the_background(board, ai, monkeypatch):
    """Through the real start(): the answer comes before the search is done."""
    import threading

    done = threading.Event()
    real_run = service.run
    monkeypatch.setattr(service, 'run', lambda b, i: (real_run(b, i), done.set()))
    ai.candidates = []

    assert client.post(PATH, json=body(), headers=monday_auth(PATH)).status_code == 200
    assert done.wait(5)
    assert board.request_statuses == ['AI Bot', 'Manual research']
