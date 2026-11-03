"""The page monday shows in the Item View, and its assets: public, served unchanged."""
import logging
import os

import pytest

from app.features.comment_builder.router import STATIC_DIR

from .conftest import client

INDEX = open(os.path.join(STATIC_DIR, 'index.html'), 'rb').read()
ASSETS = sorted(os.listdir(os.path.join(STATIC_DIR, 'assets')))


@pytest.mark.parametrize('path', ['/comment-builder', '/comment-builder/', '/comment-builder/item/42', '/comment-builder/?x=1'])
def test_the_page_is_served_without_a_token(path):
    res = client.get(path)
    assert res.status_code == 200
    assert res.content == INDEX
    assert res.headers['content-type'] == 'text/html; charset=utf-8'
    assert res.headers['cache-control'] == 'no-cache'


def test_the_page_answers_head():
    assert client.head('/comment-builder').status_code == 200


def test_index_html_asks_for_assets_that_exist():
    html = INDEX.decode()
    for name in ASSETS:
        assert f'/assets/{name}' in html


def test_the_built_page_is_the_current_sources():
    """static/ is page/build.py's output: the feed source, as written, is in the served script."""
    page = os.path.join(os.path.dirname(STATIC_DIR), 'page')
    feed = open(os.path.join(page, 'updates-feed.js'), encoding='utf-8').read()
    [script] = [n for n in ASSETS if n.startswith('index-') and n.endswith('.js')]
    built = open(os.path.join(STATIC_DIR, 'assets', script), encoding='utf-8').read()
    assert feed in built, 'run python3 -I app/features/comment_builder/page/build.py'
    assert '/api/files/upload' in built


@pytest.mark.parametrize('name', ASSETS)
@pytest.mark.parametrize('prefix', ['/assets/', '/comment-builder/assets/', '/comment-builder/item/42/assets/'])
def test_assets_are_served_unchanged_and_cached(prefix, name):
    res = client.get(prefix + name)
    assert res.status_code == 200
    assert res.content == open(os.path.join(STATIC_DIR, 'assets', name), 'rb').read()
    assert res.headers['cache-control'] == 'public, max-age=31536000, immutable'
    assert res.headers['content-type'].startswith('text/javascript' if name.endswith('.js') else 'text/css')


def test_a_missing_asset_is_a_json_404_never_the_page():
    res = client.get('/assets/index-00000000.js')
    assert res.status_code == 404
    assert res.json() == {'error': 'Not found'}


def test_an_unknown_file_under_the_page_falls_back_to_the_page():
    res = client.get('/comment-builder/favicon.ico')
    assert res.status_code == 200
    assert res.content == INDEX


@pytest.mark.parametrize('path', ['/assets/..%2F..%2Frouter.py', '/comment-builder/..%2Frouter.py', '/assets/%2E%2E/%2E%2E/service.py'])
def test_nothing_outside_the_page_is_served(path):
    res = client.get(path)
    assert b'import' not in res.content
    assert res.status_code in (200, 403, 404)
    if res.status_code == 200:
        assert res.content == INDEX


def test_the_page_is_not_a_post_target():
    assert client.post('/comment-builder').status_code == 405


def test_page_loads_are_logged_at_debug_only(caplog):
    caplog.set_level('INFO', logger='monday_apps')
    client.get('/comment-builder')
    client.get('/assets/' + ASSETS[0])
    lines = [r for r in caplog.records if r.name == 'monday_apps' and ' -> ' in r.getMessage()]
    assert all(r.levelno == logging.DEBUG for r in lines)


def test_health_names_the_secret_sources_never_a_value():
    res = client.get('/comment-builder/health')
    assert res.json() == {
        'ok': True,
        'signatureCheck': 'on',
        'secretsFound': {'OPENAI_API_KEY': ['env'], 'MONDAY_CLIENT_SECRET': ['env']},
    }
    assert 'test-client-secret' not in res.text and 'test-openai-key' not in res.text


def test_health_shows_the_signature_check_off_without_a_client_secret(monkeypatch):
    monkeypatch.delenv('MONDAY_CLIENT_SECRET')
    assert client.get('/comment-builder/health').json()['signatureCheck'] == 'off'
