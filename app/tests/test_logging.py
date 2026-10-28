"""
Structured logs: what reaches the Developer Center's Logs page.

  pytest
"""
import json
import logging

import requests

from app.core import logging as monday_logging
from app.core.logging import MondayCodeLogHandler, block_ids, request_context, to_entry


def record(message, level=logging.INFO, payload=None, exc_info=None, name='company_enrichment'):
    rec = logging.LogRecord(name, level, __file__, 1, message, None, exc_info)
    if payload is not None:
        rec.payload = payload
    return rec


def test_a_record_becomes_monday_codes_log_entry():
    entry = to_entry(record('Item 42: updated 21 columns', payload={'item_id': '42', 'columns_written': 21}))
    assert entry == {
        'method': 'info',
        'message': 'Item 42: updated 21 columns',
        'payload': {'logger': 'company_enrichment', 'item_id': '42', 'columns_written': 21},
    }


def test_levels_map_to_monday_codes_methods():
    assert to_entry(record('x', logging.WARNING))['method'] == 'warn'
    assert to_entry(record('x', logging.ERROR))['method'] == 'error'
    assert to_entry(record('x', logging.DEBUG))['method'] == 'debug'


def test_an_exception_travels_as_the_error_field():
    try:
        raise ValueError('bad column')
    except ValueError:
        import sys
        entry = to_entry(record('split failed', logging.ERROR, exc_info=sys.exc_info()))
    assert 'ValueError: bad column' in entry['error']


def test_entries_are_posted_to_monday_code(monkeypatch):
    posted = []

    class Response:
        def raise_for_status(self):
            pass

    handler = MondayCodeLogHandler(to_stdout=False)
    monkeypatch.setattr(handler.session, 'post', lambda url, data, headers, timeout: posted.append((url, json.loads(data))) or Response())

    handler._send(to_entry(record('hello', payload={'board_id': '5106281544'})))

    assert posted == [(monday_logging.MONDAY_CODE_LOGS_URL, {
        'method': 'info', 'message': 'hello', 'payload': {'logger': 'company_enrichment', 'board_id': '5106281544'},
    })]


def test_off_monday_code_it_falls_back_to_json_lines_on_stdout(monkeypatch, capsys):
    def refused(*args, **kwargs):
        raise requests.ConnectionError('connection refused')

    handler = MondayCodeLogHandler(to_stdout=False)
    monkeypatch.setattr(handler.session, 'post', refused)

    handler._send(to_entry(record('first', payload={'item_id': '1'})))
    handler._send(to_entry(record('second')))

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line['message'] for line in lines] == [
        'monday-code logs not reachable (connection refused) - logging to stdout',
        'first',
        'second',
    ]
    assert lines[1] == {'level': 'info', 'message': 'first', 'payload': {'logger': 'company_enrichment', 'item_id': '1'}}
    assert handler.to_stdout, 'one failure switches to stdout for good, not a timeout per line'


def test_payload_values_that_are_not_json_do_not_break_logging(capsys):
    handler = MondayCodeLogHandler(to_stdout=True)
    handler._send(to_entry(record('odd', payload={'when': object()})))
    assert json.loads(capsys.readouterr().out)['message'] == 'odd'


def test_lines_carry_the_request_they_belong_to(monkeypatch):
    sent = []
    handler = MondayCodeLogHandler(to_stdout=True)
    monkeypatch.setattr(handler.entries, 'put', sent.append)

    token = request_context.set({'request_id': 'abc123', 'feature': 'customer_name_split'})
    try:
        handler.emit(record('[kunden item 42] split', payload={'item_id': '42'}, name='customer_name_split'))
    finally:
        request_context.reset(token)
    handler.emit(record('startup'))

    assert sent[0]['payload'] == {
        'logger': 'customer_name_split', 'request_id': 'abc123', 'feature': 'customer_name_split', 'item_id': '42',
    }
    assert sent[1]['payload'] == {'logger': 'company_enrichment'}, 'outside a request there is no context'


def test_block_ids_reads_both_block_shapes_and_the_action_uuid():
    body = json.dumps({
        'payload': {'inputFields': {'boardId': 5106281544, 'itemId': {'value': 42}}},
        'runtimeMetadata': {'actionUuid': 'uuid-1'},
    }).encode()
    assert block_ids(body) == {'board_id': '5106281544', 'item_id': '42', 'action_uuid': 'uuid-1'}

    legacy = json.dumps({'payload': {'inboundFieldValues': {'boardId': 1, 'itemId': 2}}}).encode()
    assert block_ids(legacy) == {'board_id': '1', 'item_id': '2'}


def test_block_ids_never_breaks_on_odd_bodies():
    for body in (b'', b'{bad', b'[]', b'"x"', b'{"payload": []}', b'{"payload": {"inputFields": [1]}}'):
        assert block_ids(body) == {}
