"""
Features are independent: each imports nothing of another, runs alone, and owns
its own paths. Flask is gone.

  pytest
"""
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.router import FEATURES
from app.core.testing import monday_auth
from app.features.company_enrichment.router import FEATURE as company_enrichment
from app.features.customer_name_split.router import FEATURE as customer_name_split
from app.features.vendor_name_split.router import FEATURE as vendor_name_split
from main import create_app

from .conftest import block_body

ROOT = Path(__file__).resolve().parents[2]


FEATURE_NAMES = [feature.name for feature in FEATURES]


@pytest.mark.parametrize('feature', FEATURE_NAMES)
def test_importing_one_feature_imports_no_other(feature):
    others = [name for name in FEATURE_NAMES if name != feature]
    code = (
        f'import sys; import app.features.{feature}.router; '
        f'loaded = [m for m in sys.modules if m.split(".")[2:3] and m.split(".")[2] in {others!r}]; '
        f'assert not loaded, loaded'
    )
    subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True)


@pytest.mark.parametrize('feature, own_path', [
    (company_enrichment, '/company-enrichment'),
    (customer_name_split, '/customer-name-split'),
    (vendor_name_split, '/vendor-name-split'),
])
def test_each_feature_runs_alone(calls, feature, own_path):
    other_paths = {'/company-enrichment', '/customer-name-split', '/vendor-name-split'} - {own_path}
    with TestClient(create_app([feature])) as alone:
        assert alone.post(own_path, json=block_body(), headers=monday_auth(own_path)).status_code == 200
        for other_path in other_paths:
            assert alone.post(other_path, json=block_body(), headers=monday_auth(other_path)).status_code == 404
        assert alone.get('/health').text == 'OK'


def test_no_two_features_claim_the_same_route():
    claimed = {}
    for feature in FEATURES:
        for route in feature.router.routes:
            for method in route.methods:
                key = (method, route.path)
                assert key not in claimed, f'{key} claimed by {claimed.get(key)} and {feature.name}'
                claimed[key] = feature.name


def test_feature_names_are_unique():
    names = [feature.name for feature in FEATURES]
    assert len(names) == len(set(names))


def test_fastapi_is_the_only_http_framework():
    requirements = (ROOT / 'requirements.txt').read_text().lower()
    for package in ('flask', 'a2wsgi', 'waitress', 'werkzeug'):
        assert package not in requirements

    for source in (ROOT / 'app').rglob('*.py'):
        text = source.read_text()
        for package in ('flask', 'a2wsgi', 'waitress'):
            assert f'import {package}' not in text and f'from {package}' not in text, source
