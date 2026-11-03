"""📎 From Computer: the file goes to monday's file API, only for the session user's own update on that item."""
import io
import json
import urllib.error

import pytest

from app.core.testing import session_auth
from app.features.comment_builder import files, router

from .conftest import FakeResponse, client

ITEM, UPDATE, REPLY, OTHERS = '555', '777', '778', '779'
ASSET_URL = 'https://zvg-group.monday.com/protected_static/21186107/resources/99/Offer.docx'


class FakeMonday:
    """monday's GraphQL and file endpoints in memory. Updates on ITEM: UPDATE (user 2, with REPLY) and OTHERS (user 9)."""

    def __init__(self):
        self.queries = []
        self.uploads = []
        self.errors = None

    def urlopen(self, req, timeout=None):
        assert timeout == files.TIMEOUT_SECONDS
        headers = {k.lower(): v for k, v in req.header_items()}
        if req.full_url == files.API_URL:
            self.queries.append({'headers': headers, 'body': json.loads(req.data)})
            updates = [
                {'id': UPDATE, 'creator_id': 2, 'replies': [{'id': REPLY, 'creator_id': 2}]},
                {'id': OTHERS, 'creator_id': 9, 'replies': []},
            ]
            return FakeResponse({'errors': self.errors} if self.errors else {'data': {'items': [{'updates': updates}]}})
        assert req.full_url == files.FILE_URL
        self.uploads.append({'headers': headers, 'body': req.data})
        return FakeResponse({'data': {'add_file_to_update': {'id': '99', 'name': 'Offer.docx', 'url': ASSET_URL}}})


@pytest.fixture
def monday(monkeypatch):
    fake = FakeMonday()
    monkeypatch.setattr(files.urllib.request, 'urlopen', fake.urlopen)
    return fake


def upload(content=b'PK\x03\x04 docx bytes', update=UPDATE, item=ITEM, name='Offer.docx',
           content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document', headers=None, **token):
    return client.post('/api/files/upload', params={'updateId': update, 'itemId': item, 'name': name}, content=content,
                       headers={'Content-Type': content_type, **(session_auth(**token) if headers is None else headers)})


def test_uploads_the_file_to_the_update_and_returns_mondays_link(monday):
    res = upload()

    assert res.status_code == 200
    assert res.json() == {'id': '99', 'name': 'Offer.docx', 'url': ASSET_URL}
    [sent] = monday.uploads
    assert sent['headers']['authorization'] == 'test-api-token'
    assert sent['headers']['content-type'].startswith('multipart/form-data; boundary=')
    body = sent['body']
    assert b'add_file_to_update (update_id: 777, file: $file) { id name url }' in body
    assert b'name="variables[file]"; filename="Offer.docx"' in body
    assert b'Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document' in body
    assert b'PK\x03\x04 docx bytes' in body


def test_it_first_asks_monday_whose_update_it_is_on_that_item(monday):
    upload()
    [query] = monday.queries
    assert query['body']['variables'] == {'itemId': [ITEM]}
    assert 'replies { id creator_id }' in query['body']['query']
    assert query['headers']['authorization'] == 'test-api-token'


def test_a_reply_by_the_user_works_too(monday):
    assert upload(update=REPLY).status_code == 200
    assert b'update_id: 778' in monday.uploads[0]['body']


def test_someone_elses_update_is_403_and_nothing_is_uploaded(monday):
    res = upload(update=OTHERS)
    assert res.status_code == 403
    assert res.json() == {'error': 'You can attach files only to your own updates.'}
    assert monday.uploads == []


def test_an_update_not_on_the_item_is_404_and_nothing_is_uploaded(monday):
    res = upload(update='123456')
    assert res.status_code == 404
    assert monday.uploads == []


@pytest.mark.parametrize('update, item', [('', ITEM), (UPDATE, ''), ('7 } } mutation {', ITEM), (UPDATE, 'abc'), ('1' * 21, ITEM)])
def test_ids_must_be_monday_ids(monday, update, item):
    res = upload(update=update, item=item)
    assert res.status_code == 400
    assert monday.queries == [] and monday.uploads == []


def test_an_empty_file_is_400(monday):
    res = upload(content=b'')
    assert res.status_code == 400
    assert res.json() == {'error': 'The file is empty.'}


def test_a_file_over_the_limit_is_413(monday, monkeypatch):
    monkeypatch.setattr(router, 'MAX_FILE', 10)
    res = upload(content=b'x' * 11)
    assert res.status_code == 413
    assert monday.queries == []


def test_no_session_token_is_401(monday):
    assert upload(headers={}).status_code == 401
    assert monday.queries == []


def test_no_monday_token_is_500(monday, monkeypatch):
    monkeypatch.delenv('MONDAY_API_TOKEN')
    res = upload()
    assert res.status_code == 500
    assert 'MONDAY_API_TOKEN' in res.json()['error']


def test_it_needs_no_openai_key(monday, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY')
    assert upload().status_code == 200


@pytest.mark.parametrize('name, sent', [
    ('Ang"ebot\r\nX-Evil: 1.pdf', b'filename="Ang ebot  X-Evil: 1.pdf"'),
    ('C:\\Users\\me\\Offer.docx', b'filename="Offer.docx"'),
    ('../../etc/Offer.docx', b'filename="Offer.docx"'),
    ('Übersicht 2026.xlsx', 'filename="Übersicht 2026.xlsx"'.encode()),
])
def test_the_file_name_is_made_safe(monday, name, sent):
    assert upload(name=name).status_code == 200
    assert sent in monday.uploads[0]['body']


def test_a_name_that_is_empty_after_cleaning_is_400(monday):
    assert upload(name='\r\n').status_code == 400


def test_an_odd_content_type_is_sent_as_octet_stream(monday):
    upload(content_type='text/html\r\nX-Evil: 1')
    assert b'Content-Type: application/octet-stream' in monday.uploads[0]['body']


def test_a_monday_error_is_502_with_its_message(monday):
    monday.errors = [{'message': 'User unauthorized to perform action'}]
    res = upload()
    assert res.status_code == 502
    assert res.json() == {'error': 'monday API error: User unauthorized to perform action'}


def test_monday_unreachable_is_502(monkeypatch):
    def down(req, timeout=None):
        raise urllib.error.URLError('timed out')

    monkeypatch.setattr(files.urllib.request, 'urlopen', down)
    res = upload()
    assert res.status_code == 502
    assert 'could not be reached' in res.json()['error']


def test_an_http_error_from_monday_is_502(monkeypatch):
    def refused(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, 'no', {}, io.BytesIO(b'{"error_message":"Not Authenticated"}'))

    monkeypatch.setattr(files.urllib.request, 'urlopen', refused)
    res = upload()
    assert res.status_code == 502
    assert res.json() == {'error': 'monday API error: Not Authenticated'}


def test_30_uploads_a_minute_per_user_then_429(monday):
    for _ in range(30):
        assert upload().status_code == 200
    res = upload()
    assert res.status_code == 429
    assert res.json() == {'error': 'Too many uploads. Please wait a minute.'}


def test_the_log_names_the_update_never_the_token_or_content(monday, caplog):
    caplog.set_level('INFO')
    upload(content=b'secret contract text')
    lines = [r for r in caplog.records if r.name == 'comment_builder']
    assert any(r.getMessage().startswith('File attached to update 777') for r in lines)
    everything = ' '.join(f'{r.getMessage()} {getattr(r, "payload", "")}' for r in caplog.records)
    assert 'test-api-token' not in everything and 'secret contract text' not in everything
