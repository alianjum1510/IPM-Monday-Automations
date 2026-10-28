"""Settings every test runs with. Tests that need others set them with monkeypatch."""
import logging
import os

import pytest

from app.core import config
from app.core.testing import TEST_BASE_URL, TEST_SIGNING_SECRET

os.environ.setdefault('MONDAY_SIGNING_SECRET', TEST_SIGNING_SECRET)
os.environ.setdefault('MONDAY_JWT_AUDIENCE_BASE_URLS', TEST_BASE_URL)
os.environ.setdefault('MONDAY_API_TOKEN', 'test-api-token')
os.environ.setdefault('OPENAI_API_KEY', 'test-openai-key')


@pytest.fixture(autouse=True)
def quiet_monday_code_log_handler():
    """setup_logging()'s handler would print every line from its own thread; caplog still sees them."""
    from app.core.logging import MondayCodeLogHandler

    root = logging.getLogger()
    root.handlers[:] = [h for h in root.handlers if not isinstance(h, MondayCodeLogHandler)]
    yield


@pytest.fixture(autouse=True)
def no_monday_code_service(monkeypatch):
    """No test reaches the monday-code settings service; a test that needs it fakes _from_monday_code."""
    async def nothing(keys):
        return {}

    monkeypatch.setattr(config, '_from_monday_code', nothing)
    monkeypatch.setattr(config, '_cache', {})
