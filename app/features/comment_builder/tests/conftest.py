import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from app.core.testing import session_auth
from app.features.comment_builder import ratelimit, service
from app.features.comment_builder.router import FEATURE
from main import create_app

# This feature alone, as the deployment serves it: proves it needs no other feature.
client = TestClient(create_app([FEATURE]))


def post(path, json=None, headers=None, **token):
    return client.post(path, json=json, headers=session_auth(**token) if headers is None else headers)


class FakeOpenAI:
    """OpenAI chat completions in memory: answers `content` (or fails with `status`) and records each request."""

    def __init__(self):
        self.content = 'A drafted update.'
        self.status = 200
        self.error = None
        self.requests = []

    def urlopen(self, req, timeout=None):
        assert req.full_url == service.OPENAI_URL
        assert timeout == service.OPENAI_TIMEOUT_SECONDS
        self.requests.append({'headers': dict(req.header_items()), 'body': json.loads(req.data)})
        if self.status != 200:
            body = json.dumps({'error': {'message': self.error}} if self.error else {}).encode()
            raise urllib.error.HTTPError(req.full_url, self.status, 'error', {}, io.BytesIO(body))
        return FakeResponse({'choices': [{'message': {'content': self.content}}]})

    @property
    def last(self):
        return self.requests[-1]['body']


class FakeResponse:
    status = 200

    def __init__(self, data):
        self.raw = json.dumps(data).encode()

    def read(self):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def openai(monkeypatch):
    fake = FakeOpenAI()
    monkeypatch.setattr(service.urllib.request, 'urlopen', fake.urlopen)
    return fake


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    ratelimit.hits.clear()
    yield
    ratelimit.hits.clear()


@pytest.fixture(autouse=True)
def no_real_openai(monkeypatch):
    """Nothing reaches OpenAI: a test that calls it uses the `openai` fixture, which replaces this."""

    def refuse(*args, **kwargs):
        raise AssertionError('a test tried to reach the network')

    monkeypatch.setattr(service.urllib.request, 'urlopen', refuse)
