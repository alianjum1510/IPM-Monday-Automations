"""
End to end through main.app: a monday block call in, the monday and OpenAI APIs
faked at the HTTP layer, the columns that would be written out. No real board
is ever written.

  pytest
"""
import json
import logging
import threading
import time
from pathlib import Path

import httpx
import pytest
import requests

from app.core.logging import request_context
from app.core.testing import monday_auth
from app.features.company_enrichment.lib import taxonomy
from app.features.company_enrichment.services import fx
from app.core import monday_client as split_monday

ENRICHMENT_TESTS = Path(__file__).resolve().parents[1] / 'features' / 'company_enrichment' / 'tests'
BOARDS = json.loads((ENRICHMENT_TESTS / 'boards.json').read_text())['data']['boards']
WARM = next(b for b in BOARDS if b['id'] == '5100825258')

MODEL_ANSWER = """
CORRECT_NAME: ANDREAS STIHL AG & Co. KG
CORRECT_ADDRESS: Badstraße 115, 71336 Waiblingen, Deutschland
REGISTRATION_NUMBER: HRA 260269
HANDELSREGISTER_VERIFIED: Yes
HOMEPAGE: www.stihl.de
CONFIDENCE: High
CITY: Waiblingen
POSTAL_CODE: 71336
COUNTRY: Germany
COMPANY_EMAIL: info@stihl.de
"""


def id_of(title):
    return next(c['id'] for c in WARM['columns'] if c['title'] == title)


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.data


class LogContext(logging.Handler):
    """Records each line with the request context it was logged in."""

    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append((record.getMessage(), dict(request_context.get())))


@pytest.fixture
def log_context():
    handler = LogContext()
    logging.getLogger().addHandler(handler)
    yield handler
    logging.getLogger().removeHandler(handler)


@pytest.fixture
def fake_apis(monkeypatch):
    """monday GraphQL and OpenAI for the enrichment (requests), FX feeds off."""
    state = {'writes': [], 'openai_calls': 0, 'written': threading.Event()}
    item = {
        'id': '42', 'name': 'Stihl', 'state': 'active', 'board': {'id': WARM['id']},
        'column_values': [
            {'id': id_of('Company / Customer Name'), 'text': 'Stihl'},
            {'id': id_of('City'), 'text': 'Waiblingen'},
            {'id': id_of('Postal Code'), 'text': '71336'},
        ],
    }

    def fake_post(url, json=None, headers=None, timeout=None):
        if url == 'https://api.openai.com/v1/responses':
            state['openai_calls'] += 1
            if json['input'].startswith('Which country is this address in?'):
                return FakeResponse({'output_text': 'DE', 'output': []})
            return FakeResponse({'output_text': MODEL_ANSWER, 'output': [{'type': 'web_search_call'}]})
        assert url == 'https://api.monday.com/v2', url
        assert headers['Authorization'] == 'test-api-token'
        query = json['query']
        if 'query Item' in query:
            return FakeResponse({'data': {'items': [item]}})
        if 'query BoardColumns' in query:
            return FakeResponse({'data': {'boards': [WARM]}})
        if 'query BoardItems' in query:
            return FakeResponse({'data': {'boards': [{'id': '1', 'items_page': {'cursor': None, 'items': []}}]}})
        if 'mutation ChangeValues' in query:
            state['writes'].append(__import__('json').loads(json['variables']['values']))
            state['written'].set()
            return FakeResponse({'data': {'change_multiple_column_values': {'id': '42'}}})
        raise AssertionError(f'unexpected monday query: {query}')

    monkeypatch.setattr(requests, 'post', fake_post)
    monkeypatch.setattr(fx, 'get_rates', lambda: None)
    taxonomy.clear_taxonomy_cache()
    return state


def wait_for(lines, prefix, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        found = [line for line in lines if line[0].startswith(prefix)]
        if found:
            return found
        time.sleep(0.02)
    raise AssertionError(f'no log line starting with {prefix!r}')


@pytest.mark.parametrize('path', ['/', '/company-enrichment'])
def test_company_enrichment_runs_end_to_end(client, fake_apis, log_context, path):
    body = {'payload': {'inputFields': {'boardId': int(WARM['id']), 'itemId': 42}},
            'runtimeMetadata': {'actionUuid': 'action-1'}}
    res = client.post(path, json=body, headers=monday_auth(path))

    assert res.status_code == 200
    assert res.json() == {'received': True, 'boardId': WARM['id'], 'itemId': '42'}

    assert fake_apis['written'].wait(5), 'the enrichment never wrote'
    [(message, context)] = wait_for(log_context.lines, 'Background enrichment done')
    [write] = fake_apis['writes']
    assert write[id_of('Registration Number')] == 'HRA 260269'
    assert fake_apis['openai_calls'] == 2  # the address names no country: classify it, then research

    # The background thread's lines belong to the request that started it.
    [(_, request_line_context)] = [line for line in log_context.lines if line[0].startswith('Action received')]
    assert context['feature'] == 'company_enrichment'
    assert context['request_id'] == request_line_context['request_id']
    [(updated, _)] = wait_for(log_context.lines, 'Item 42: updated')
    assert 'verified=yes' in updated
    assert 'web searches: 1' in updated
    [(enriching, _)] = wait_for(log_context.lines, 'Item 42: enriching')
    assert '(country: Germany from address (city / postal code))' in enriching


@pytest.fixture
def fake_split_monday(monkeypatch):
    """monday GraphQL for the name split (httpx), one Kunden item with a long name."""
    long_name = ('Zweckverband Gemeinschaftliche Wasserversorgung und Abwasserentsorgung '
                 'Landkreis Oberallgäu Süd Kempten Immenstadt')
    state = {'mutations': []}

    def handler(request):
        payload = json.loads(request.content)
        if 'mutation' in payload['query']:
            state['mutations'].append(json.loads(payload['variables']['values']))
            return httpx.Response(200, json={'data': {'change_multiple_column_values': {'id': '42'}}})
        cols = [{'id': c, 'type': 'text', 'text': ''} for c in payload['variables']['colIds']]
        return httpx.Response(200, json={'data': {'items': [{'name': long_name, 'column_values': cols}]}})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(split_monday.httpx, 'AsyncClient',
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return state


def test_customer_name_split_runs_end_to_end(client, fake_split_monday, log_context):
    body = {'payload': {'inputFields': {'boardId': 5099245948, 'itemId': 42}}}
    res = client.post('/customer-name-split', json=body, headers=monday_auth('/customer-name-split'))

    assert res.status_code == 200
    assert res.json() == {'outputFields': {}}
    assert fake_split_monday['mutations'] == [{
        'text_mkt92ar9': 'Zweckverband Gemeinschaftliche Wasserversorgung und Abwasserentsorgung Landkreis Oberallgäu Süd',
        'text_mksb1npw': 'Kempten Immenstadt',
    }]
    [(_, context)] = [line for line in log_context.lines if line[0].startswith('[kunden item 42]')]
    assert context['feature'] == 'customer_name_split'
