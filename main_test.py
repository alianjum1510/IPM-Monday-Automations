"""
The one server in main.py: each block URL reaches its own app.

  pytest
"""
import threading

import jwt
import pytest
from fastapi.testclient import TestClient

import main

SIGNING_SECRET = 'test-signing-secret-0123456789abcdef'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('MONDAY_SIGNING_SECRET', SIGNING_SECRET)
    # `with` runs the startup, which is what loads the enrichment app.
    with TestClient(main.app) as test_client:
        yield test_client


def monday_jwt():
    return {'Authorization': jwt.encode({'accountId': 1, 'userId': 2}, SIGNING_SECRET, algorithm='HS256')}


@pytest.mark.parametrize('path', ['/', '/health'])
def test_health_check_answers_get_and_head(client, path):
    assert client.get(path).text == 'OK'
    assert client.head(path).status_code == 200


@pytest.mark.parametrize('path', [
    '/company-enrichment', '/company-enrichment/',
    # The enrichment block's URL before the merge: the bare Version URL.
    '/',
])
def test_company_enrichment_acks_and_runs_in_the_background(client, monkeypatch, path):
    import index

    started = threading.Event()
    calls = []

    def fake_enrich_item(board_id, item_id):
        calls.append((board_id, item_id))
        started.set()
        return {'success': True}

    monkeypatch.setattr(index, 'enrich_item', fake_enrich_item)

    res = client.post(path, json={'payload': {'inputFields': {'boardId': 5106281544, 'itemId': 42}}})

    assert res.status_code == 200
    assert res.json() == {'received': True, 'boardId': '5106281544', 'itemId': '42'}
    assert started.wait(5), 'the enrichment never started'
    assert calls == [('5106281544', '42')]


def test_company_enrichment_still_requires_an_item(client):
    res = client.post('/company-enrichment', json={'payload': {'inputFields': {'boardId': 5106281544}}})
    assert res.status_code == 400
    assert res.json() == {'error': 'boardId and itemId are required'}


@pytest.mark.parametrize('path', [
    '/customer-name-split', '/customer-name-split/', '/customer-name-split/monday/split-name',
    # The name split's URL before the merge, as its old README set it up.
    '/monday/split-name',
])
def test_customer_name_split_is_reached_and_checks_the_monday_jwt(client, path):
    # No JWT: the name split app's own auth rejects it.
    assert client.post(path, json={}).status_code == 401

    # A valid JWT but no item: the name split app's own input check answers.
    res = client.post(path, json={'payload': {'inputFields': {'boardId': 5106281544}}}, headers=monday_jwt())
    assert res.status_code == 400
    assert res.json()['notificationErrorTitle'] == 'Missing input'


def test_the_two_apps_do_not_answer_each_others_paths(client):
    # The enrichment block posts no JWT, so a request reaching the name split would be a 401.
    assert client.post('/company-enrichment', json={}).status_code == 400
    # The bare URL is the enrichment block's, and must never run the name split.
    assert client.post('/', json={}).status_code == 400
    assert client.post('/', json={}).json() == {'error': 'boardId and itemId are required'}
    assert client.post('/unknown', json={}).status_code == 404
