"""Every /api/ai call carries monday's session token for this app, signed with its Client Secret."""
import pytest

from app.core.testing import monday_auth, session_token

from .conftest import post

ROUTES = ['/api/ai/write', '/api/ai/summarize', '/api/ai/autofill']
BODY = {'prompt': 'x', 'text': 'x', 'comment': 'x'}


def test_a_valid_token_passes(openai):
    assert post('/api/ai/write', BODY).status_code == 200


def test_the_bearer_prefix_is_accepted(openai):
    assert post('/api/ai/write', BODY, headers={'Authorization': 'Bearer ' + session_token()}).status_code == 200


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('headers', [{}, {'Authorization': ''}, {'Authorization': 'not-a-token'}, {'Authorization': 'a.b'}])
def test_a_missing_or_malformed_token_is_401(route, headers):
    res = post(route, BODY, headers=headers)
    assert res.status_code == 401
    assert res.json() == {'error': 'Missing monday session token. Open this page inside monday.'}


@pytest.mark.parametrize('route', ROUTES)
def test_a_token_signed_with_another_secret_is_401(route):
    res = post(route, BODY, secret='some-other-apps-client-secret-0123456789')
    assert res.status_code == 401
    assert res.json() == {'error': 'Invalid monday session token. Reload the page.'}


def test_an_unreadable_token_is_401():
    res = post('/api/ai/write', BODY, headers={'Authorization': 'abc.def.ghi'})
    assert res.status_code == 401
    assert res.json() == {'error': 'Invalid monday session token. Reload the page.'}


def test_an_expired_token_is_401():
    res = post('/api/ai/write', BODY, expires_in=-60)
    assert res.status_code == 401
    assert res.json() == {'error': 'monday session expired. Reload the page.'}


def test_a_token_without_exp_is_still_accepted(openai):
    # As the original server: exp is checked when present.
    assert post('/api/ai/write', BODY, exp=None).status_code == 200


def test_a_token_of_another_app_is_403():
    res = post('/api/ai/write', BODY, app_id=11942098)  # the old Comment Builder app
    assert res.status_code == 403
    assert res.json() == {'error': 'This session belongs to another app.'}


def test_the_app_id_is_a_setting(openai, monkeypatch):
    monkeypatch.setenv('MONDAY_APP_ID', '11942098')
    assert post('/api/ai/write', BODY, app_id=11942098).status_code == 200
    assert post('/api/ai/write', BODY).status_code == 403


def test_a_block_jwt_is_not_a_session_token():
    """The Signing Secret's JWT is for the automation blocks; it never opens the AI."""
    res = post('/api/ai/write', BODY, headers=monday_auth('/api/ai/write'))
    assert res.status_code == 401


def test_without_a_client_secret_nothing_is_let_through(monkeypatch, openai):
    monkeypatch.delenv('MONDAY_CLIENT_SECRET')
    res = post('/api/ai/write', BODY)
    assert res.status_code == 500
    assert 'MONDAY_CLIENT_SECRET is not set' in res.json()['error']
    assert openai.requests == []


def test_the_token_is_checked_before_the_body(openai):
    res = post('/api/ai/write', headers={}, json=None)
    assert res.status_code == 401
