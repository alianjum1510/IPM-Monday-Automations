"""
Settings (app/core/config.py): process env first, then the monday-code service;
checked per feature at startup and per request; values never logged.

  pytest
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import main
from app.core import config
from app.features.company_enrichment.config.env import env
from app.features.company_enrichment.lib import taxonomy

from .conftest import post


def fake_monday_code(monkeypatch, values):
    asked = []

    async def read(keys):
        asked.append(list(keys))
        return {key: values[key] for key in keys if key in values}

    monkeypatch.setattr(config, '_from_monday_code', read)
    return asked


def test_the_process_environment_wins(monkeypatch):
    fake_monday_code(monkeypatch, {'OPENAI_MODEL': 'from-monday-code'})
    monkeypatch.setenv('OPENAI_MODEL', 'from-env')
    asyncio.run(config.load(['OPENAI_MODEL']))
    assert config.setting('OPENAI_MODEL') == 'from-env'
    assert config.source('OPENAI_MODEL') == 'env'


def test_a_key_missing_from_env_is_read_from_monday_code_once(monkeypatch):
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    asked = fake_monday_code(monkeypatch, {'OPENAI_MODEL': 'gpt-from-monday-code'})

    assert asyncio.run(config.load(['OPENAI_MODEL'])) == {'OPENAI_MODEL': 'monday-code'}
    assert config.setting('OPENAI_MODEL') == 'gpt-from-monday-code'
    assert asyncio.run(config.get_secret('OPENAI_MODEL')) == 'gpt-from-monday-code'
    assert asked == [['OPENAI_MODEL']], 'a value that was found is kept, not re-read'


def test_alternative_names_are_accepted(monkeypatch):
    monkeypatch.delenv('MONDAY_API_TOKEN')
    monkeypatch.setenv('MONDAY_API_KEY', 'old-name-token')
    assert asyncio.run(config.get_secret('MONDAY_API_TOKEN', 'MONDAY_API_KEY')) == 'old-name-token'
    assert env.monday.api_token == 'old-name-token'


def test_enrichment_settings_are_read_when_used_not_on_import(monkeypatch):
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    assert env.openai.model == 'gpt-4o'
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-test')
    assert env.openai.model == 'gpt-test'

    monkeypatch.setenv('OPENAI_TIMEOUT_MS', 'not a number')
    assert env.openai.timeout_ms == 240000
    monkeypatch.setenv('BOARD_ITEM_DELAY_MS', '250')
    assert env.board_item_delay_ms == 250
    monkeypatch.setenv('LIFECYCLE_STAGE_SOURCES', 'Inbound, New ,')
    assert env.lifecycle_stage_sources == ['Inbound', 'New']

    monkeypatch.setenv('TAXONOMY_TTL_MS', '5000')
    assert taxonomy.ttl_ms() == 5000


def test_a_setting_served_by_monday_code_reaches_the_enrichment(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY')
    fake_monday_code(monkeypatch, {'OPENAI_API_KEY': 'sk-from-monday-code'})
    asyncio.run(config.load(['OPENAI_API_KEY']))
    assert env.openai.api_key == 'sk-from-monday-code'


def startup_lines(caplog):
    with TestClient(main.app):
        pass
    return [r for r in caplog.records if r.name == 'monday_apps']


def test_startup_names_each_features_missing_settings(monkeypatch, caplog):
    caplog.set_level('INFO')
    monkeypatch.delenv('OPENAI_API_KEY')

    lines = startup_lines(caplog)
    messages = [r.getMessage() for r in lines]

    assert 'Missing environment variables (company_enrichment): OPENAI_API_KEY' in messages
    assert 'Config OK (customer_name_split)' in messages, 'one feature missing a key does not hide the other'


def test_startup_logs_where_settings_came_from_but_never_a_value(monkeypatch, caplog):
    caplog.set_level('DEBUG')
    monkeypatch.delenv('OPENAI_API_KEY')
    fake_monday_code(monkeypatch, {'OPENAI_API_KEY': 'sk-super-secret-value'})

    lines = startup_lines(caplog)
    [found] = [r for r in lines if r.getMessage().startswith('Settings found')]
    assert found.payload['sources']['OPENAI_API_KEY'] == 'monday-code'
    assert found.payload['sources']['MONDAY_SIGNING_SECRET'] == 'env'

    everything = json.dumps([(r.getMessage(), getattr(r, 'payload', None)) for r in caplog.records], default=str)
    for secret in ('sk-super-secret-value', 'test-signing-secret-0123456789abcdef', 'test-api-token'):
        assert secret not in everything


def test_enrichment_without_its_openai_key_is_a_monday_error_and_never_starts(client, calls, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY')
    res = post(client, '/company-enrichment')
    assert res.status_code == 400
    assert res.json()['severityCode'] == 4000
    assert 'OPENAI_API_KEY' in res.json()['notificationErrorDescription']
    assert not calls.enrichment_started.wait(0.3)


def test_the_split_does_not_need_the_enrichments_openai_key(client, calls, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY')
    assert post(client, '/customer-name-split').status_code == 200


@pytest.mark.parametrize('path', ['/company-enrichment', '/customer-name-split'])
def test_a_missing_key_is_looked_up_again_on_the_next_request(client, calls, monkeypatch, path):
    """Set in the Developer Center after startup, found without a restart (as before the refactor)."""
    monkeypatch.delenv('MONDAY_API_TOKEN')
    assert post(client, path).status_code == 400

    fake_monday_code(monkeypatch, {'MONDAY_API_TOKEN': 'token-added-later'})
    assert post(client, path).status_code == 200
