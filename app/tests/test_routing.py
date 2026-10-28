"""
The one server in main.py: each block's route reaches its own feature.

  pytest
"""
import pytest

from .conftest import BOARD_ID, ENRICHMENT_PATHS, FEATURE_PATHS, SPLIT_PATHS, block_body, post


@pytest.mark.parametrize('path', ['/', '/health'])
def test_health_check_answers_get_and_head_without_a_token(client, path):
    assert client.get(path).text == 'OK'
    assert client.head(path).status_code == 200


@pytest.mark.parametrize('path', ENRICHMENT_PATHS)
def test_company_enrichment_acks_and_runs_in_the_background(client, calls, path):
    res = post(client, path)

    assert res.status_code == 200
    assert res.json() == {'received': True, 'boardId': str(BOARD_ID), 'itemId': '42'}
    assert calls.enrichment_started.wait(5), 'the enrichment never started'
    assert calls.enrichment == [(str(BOARD_ID), '42')]
    assert calls.split == []


@pytest.mark.parametrize('path', SPLIT_PATHS)
def test_customer_name_split_runs_on_its_routes(client, calls, path):
    res = post(client, path)

    assert res.status_code == 200
    assert res.json() == {'outputFields': {}}
    assert calls.split == [(BOARD_ID, 42)]
    assert calls.enrichment == []


def test_the_same_board_and_item_reach_different_features_by_route(client, calls):
    """The board id never picks the feature: one board runs both automations."""
    post(client, '/customer-name-split')
    post(client, '/company-enrichment')

    assert calls.enrichment_started.wait(5)
    assert calls.split == [(BOARD_ID, 42)]
    assert calls.enrichment == [(str(BOARD_ID), '42')]


@pytest.mark.parametrize('path', FEATURE_PATHS)
def test_a_payload_cannot_choose_the_feature(client, calls, path):
    body = block_body(feature='customer_name_split' if path in ENRICHMENT_PATHS else 'company_enrichment')
    body['blockKind'] = 'action'
    assert post(client, path, json=body).status_code == 200

    if path in ENRICHMENT_PATHS:
        assert calls.enrichment_started.wait(5)
        assert calls.split == []
    else:
        assert calls.enrichment == []


def test_company_enrichment_still_requires_an_item(client, calls):
    res = post(client, '/company-enrichment', json={'payload': {'inputFields': {'boardId': BOARD_ID}}})
    assert res.status_code == 400
    assert res.json() == {'error': 'boardId and itemId are required'}
    assert calls.enrichment == []


@pytest.mark.parametrize('content', [b'{not json', b'', b'[]', b'"text"'])
def test_company_enrichment_malformed_body_is_a_400_not_a_crash(client, calls, content):
    from app.core.testing import monday_auth

    res = client.post('/company-enrichment', content=content,
                      headers={**monday_auth('/company-enrichment'), 'Content-Type': 'application/json'})
    assert res.status_code == 400
    assert res.json() == {'error': 'boardId and itemId are required'}
    assert calls.enrichment == []


def test_company_enrichment_rejects_an_oversized_body(client, calls):
    res = post(client, '/company-enrichment', json=block_body(padding='x' * (1024 * 1024)))
    assert res.status_code == 413
    assert calls.enrichment == []


@pytest.mark.parametrize('path', ['/unknown', '/company-enrichment/extra', '/customer-name-split/monday/split-name'])
def test_unknown_routes_are_404(client, calls, path):
    assert post(client, path).status_code == 404
    assert client.get(path).status_code == 404
    assert calls.enrichment == [] and calls.split == []


@pytest.mark.parametrize('path', FEATURE_PATHS)
def test_no_route_answers_with_a_redirect(client, calls, path):
    res = post(client, path)
    assert res.status_code == 200
    assert not res.history, 'monday is not guaranteed to follow a redirect on a POST'


def test_health_routes_do_not_accept_posts_to_health(client):
    assert client.post('/health').status_code == 405


@pytest.mark.parametrize('path, routed_to', [
    ('/', 'company_enrichment'),
    ('/company-enrichment', 'company_enrichment'),
    ('/customer-name-split', 'customer_name_split'),
    ('/monday/split-name', 'customer_name_split'),
])
def test_every_request_is_logged_with_the_feature_that_answered(client, calls, caplog, path, routed_to):
    caplog.set_level('INFO', logger='monday_apps')

    post(client, path)

    [line] = [r for r in caplog.records if r.name == 'monday_apps' and r.getMessage().startswith('POST')]
    assert line.getMessage().startswith(f'POST {path} -> {routed_to} 200 ')
    assert line.payload['routed_to'] == routed_to
    assert line.payload['board_id'] == str(BOARD_ID)
    assert line.payload['item_id'] == '42'
    assert isinstance(line.payload['duration_ms'], int)


def test_a_rejected_request_is_still_logged_with_its_feature(client, calls, caplog):
    caplog.set_level('INFO', logger='monday_apps')
    client.post('/customer-name-split', json=block_body())

    [line] = [r for r in caplog.records if r.name == 'monday_apps' and r.getMessage().startswith('POST')]
    assert line.getMessage().startswith('POST /customer-name-split -> customer_name_split 401 ')


def test_an_unknown_route_is_logged_as_no_app(client, caplog):
    caplog.set_level('INFO', logger='monday_apps')
    client.post('/unknown', json={})
    [line] = [r for r in caplog.records if r.name == 'monday_apps' and r.getMessage().startswith('POST')]
    assert line.getMessage().startswith('POST /unknown -> no app 404 ')


def test_health_checks_are_not_logged_at_info(client, caplog):
    caplog.set_level('INFO', logger='monday_apps')
    client.head('/health')
    assert not [r for r in caplog.records if r.name == 'monday_apps' and 'health check' in r.getMessage()]
