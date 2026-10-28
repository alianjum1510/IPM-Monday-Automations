"""
The monday JWT check (app/core/security.py), on every feature route.

  pytest
"""
import json
import logging

import pytest

from app.core.testing import TEST_BASE_URL, monday_token

from .conftest import ENRICHMENT_PATHS, FEATURE_PATHS, block_body, post

OTHER_FEATURE_PATH = {path: '/customer-name-split' if path in ENRICHMENT_PATHS else '/company-enrichment'
                      for path in FEATURE_PATHS}


def ran(calls, path):
    if path in ENRICHMENT_PATHS:
        # The route starts the thread before it answers, so a short wait is enough either way.
        return calls.enrichment_started.wait(0.5)
    return bool(calls.split)


@pytest.mark.parametrize('path', FEATURE_PATHS)
def test_a_valid_token_for_the_route_is_accepted(client, calls, path):
    assert post(client, path).status_code == 200
    assert ran(calls, path)


@pytest.mark.parametrize('path', FEATURE_PATHS)
def test_bearer_prefix_is_accepted(client, calls, path):
    res = client.post(path, json=block_body(), headers={'Authorization': f'Bearer {monday_token(path)}'})
    assert res.status_code == 200


@pytest.mark.parametrize('path', FEATURE_PATHS)
def test_missing_token_is_401(client, calls, path):
    assert client.post(path, json=block_body()).status_code == 401
    assert not ran(calls, path)


@pytest.mark.parametrize('path', FEATURE_PATHS)
@pytest.mark.parametrize('case, kwargs', [
    ('wrong signature', {'secret': 'another-apps-signing-secret-0123456789'}),
    ('expired', {'expires_in': -3600}),
    ('no exp', {'exp': None}),
    ('aud of another deployment', {'base_url': 'https://someone-else.us.monday.app'}),
])
def test_invalid_token_is_401(client, calls, path, case, kwargs):
    assert post(client, path, **kwargs).status_code == 401, case
    assert not ran(calls, path)


@pytest.mark.parametrize('path', FEATURE_PATHS)
def test_a_token_for_the_other_features_route_is_401(client, calls, path):
    """A token monday minted for one block cannot be replayed against another block's route."""
    assert post(client, path, auth_path=OTHER_FEATURE_PATH[path]).status_code == 401
    assert not ran(calls, path)


def test_garbage_token_is_401(client, calls):
    res = client.post('/customer-name-split', json=block_body(), headers={'Authorization': 'not-a-jwt'})
    assert res.status_code == 401


def test_aud_with_trailing_slash_or_query_matches(client, calls):
    aud = f'{TEST_BASE_URL}/customer-name-split/?x=1'
    assert post(client, '/customer-name-split', aud=aud).status_code == 200


def test_any_listed_base_url_is_accepted(client, calls, monkeypatch):
    monkeypatch.setenv('MONDAY_JWT_AUDIENCE_BASE_URLS', f'https://live.monday.app, {TEST_BASE_URL}/')
    assert post(client, '/customer-name-split').status_code == 200
    assert post(client, '/customer-name-split', base_url='https://live.monday.app').status_code == 200


@pytest.mark.parametrize('path', FEATURE_PATHS)
def test_missing_signing_secret_is_a_monday_error_not_a_retried_500(client, calls, monkeypatch, path):
    monkeypatch.delenv('MONDAY_SIGNING_SECRET')
    res = post(client, path)
    assert res.status_code == 400
    assert res.json()['severityCode'] == 4000
    assert res.json()['notificationErrorTitle'] == 'Server misconfigured'
    assert not ran(calls, path)


def test_enforce_mode_without_base_urls_is_a_monday_error(client, calls, monkeypatch):
    monkeypatch.delenv('MONDAY_JWT_AUDIENCE_BASE_URLS')
    res = post(client, '/customer-name-split')
    assert res.status_code == 400
    assert 'MONDAY_JWT_AUDIENCE_BASE_URLS' in res.json()['notificationErrorDescription']


@pytest.mark.parametrize('path', FEATURE_PATHS)
def test_report_mode_logs_a_wrong_aud_but_lets_it_through(client, calls, monkeypatch, caplog, path):
    monkeypatch.setenv('MONDAY_JWT_AUDIENCE_MODE', 'report')
    caplog.set_level('INFO')
    wrong_aud = 'https://draft-version.us.monday.app'

    assert post(client, path, base_url=wrong_aud).status_code == 200
    assert ran(calls, path)

    [warning] = [r for r in caplog.records if r.getMessage().startswith('JWT audience not matched (report mode')]
    assert warning.payload['aud'] == wrong_aud + path
    assert warning.payload['path'] == path


@pytest.mark.parametrize('case, kwargs', [
    ('wrong signature', {'secret': 'another-apps-signing-secret-0123456789'}),
    ('expired', {'expires_in': -3600}),
    ('no exp', {'exp': None}),
])
def test_report_mode_still_enforces_signature_and_exp(client, calls, monkeypatch, case, kwargs):
    monkeypatch.setenv('MONDAY_JWT_AUDIENCE_MODE', 'report')
    assert post(client, '/customer-name-split', **kwargs).status_code == 401, case


def test_report_mode_does_not_need_base_urls(client, calls, monkeypatch):
    monkeypatch.setenv('MONDAY_JWT_AUDIENCE_MODE', 'report')
    monkeypatch.delenv('MONDAY_JWT_AUDIENCE_BASE_URLS')
    assert post(client, '/customer-name-split').status_code == 200


def test_an_unknown_mode_enforces(client, calls, monkeypatch):
    monkeypatch.setenv('MONDAY_JWT_AUDIENCE_MODE', 'off')
    assert post(client, '/customer-name-split', base_url='https://someone-else.us.monday.app').status_code == 401


def test_the_request_log_has_the_claims_but_never_the_token(client, calls, caplog):
    caplog.set_level('INFO')
    headers = {'Authorization': monday_token('/customer-name-split')}
    client.post('/customer-name-split', json=block_body(), headers=headers)

    [line] = [r for r in caplog.records if r.name == 'monday_apps' and r.getMessage().startswith('POST')]
    assert line.payload['jwt']['aud'] == f'{TEST_BASE_URL}/customer-name-split'
    assert set(line.payload['jwt']) == {'aud', 'exp', 'iat', 'accountId'}
    assert line.payload['aud_check'] == 'ok'

    everything = json.dumps([(r.getMessage(), getattr(r, 'payload', None)) for r in caplog.records], default=str)
    assert headers['Authorization'] not in everything
    assert 'short-lived-token-never-logged' not in everything


def test_a_failed_check_is_logged_as_a_warning(client, calls, caplog):
    caplog.set_level('INFO')
    post(client, '/customer-name-split', expires_in=-3600)
    assert any(r.levelno == logging.WARNING and 'JWT verification failed' in r.getMessage() for r in caplog.records)
