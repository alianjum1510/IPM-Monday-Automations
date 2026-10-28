"""
Structured logs for the Developer Center's Logs page.

Every feature logs through Python's `logging` as usual. This sends every record
to the monday-code service's /logs endpoint, which shows it on the Logs page
with its fields in the "payload" column (a plain print() arrives with payload null):

  log.info('Item 42: updated 21 columns', extra={'payload': {'item_id': '42', 'columns_written': 21}})

Each line also carries the request it belongs to - `request_id` and `feature` -
so one automation run can be followed end to end, background thread included.

Sending happens on a background thread, so a log call never waits on the
network - not in a request, not in an enrichment run.

Off monday-code (local runs, tests) the service is not there: the first failed
send switches to stdout, one JSON line per record. LOG_TARGET=stdout forces
that on monday-code too, should the Logs page not show the records.

RequestLogMiddleware writes one line per request: which feature answered it,
the board and item, the status and how long it took.
"""
import contextvars
import json
import logging
import os
import queue
import sys
import threading
import time
import traceback
import uuid

import requests

# Where the monday-code SDK (monday_code.LogsApi) writes its logs.
MONDAY_CODE_LOGS_URL = 'http://localhost:59999/logs'

LEVELS = {
    logging.DEBUG: 'debug',
    logging.INFO: 'info',
    logging.WARNING: 'warn',
    logging.ERROR: 'error',
    logging.CRITICAL: 'error',
}

# {'request_id': ..., 'feature': ...} for the request being handled. Copied into
# a background thread with contextvars.copy_context(), so its lines carry it too.
request_context = contextvars.ContextVar('monday_request', default={})

log = logging.getLogger('monday_apps')


def set_feature(name):
    """Tags every line logged for the rest of this request with the feature handling it."""
    request_context.set({**request_context.get(), 'feature': name})


def to_entry(record):
    """A log record as monday-code's /logs takes it: message, method (level), payload, error."""
    entry = {
        'method': LEVELS.get(record.levelno, 'info'),
        'message': record.getMessage(),
        'payload': {
            'logger': record.name,
            **(getattr(record, 'context', None) or {}),
            **(getattr(record, 'payload', None) or {}),
        },
    }
    if record.exc_info:
        entry['error'] = ''.join(traceback.format_exception(*record.exc_info))
    return entry


class MondayCodeLogHandler(logging.Handler):
    """Hands each record to a background thread that sends it to monday-code, or prints it."""

    def __init__(self, to_stdout=None):
        super().__init__()
        if to_stdout is None:
            to_stdout = os.environ.get('LOG_TARGET', '').strip().lower() == 'stdout'
        self.to_stdout = to_stdout
        self.entries = queue.Queue()
        self.session = requests.Session()
        self.lock = threading.Lock()
        threading.Thread(target=self._send_forever, name='monday-code-logs', daemon=True).start()

    def emit(self, record):
        try:
            # Read here, on the thread that logged: the sender thread has no request context.
            record.context = request_context.get()
            self.entries.put(to_entry(record))
        except Exception:  # noqa: BLE001 - a broken log call must never break the app
            self.handleError(record)

    def close(self):
        """Sends what is still queued, so the last lines before a shutdown are not lost."""
        while not self.entries.empty():
            self._send(self.entries.get())
        super().close()

    def _send_forever(self):
        while True:
            self._send(self.entries.get())

    def _send(self, entry):
        with self.lock:
            if not self.to_stdout:
                try:
                    res = self.session.post(
                        MONDAY_CODE_LOGS_URL,
                        data=json.dumps(entry, default=str),
                        headers={'Content-Type': 'application/json'},
                        timeout=2,
                    )
                    res.raise_for_status()
                    return
                except requests.RequestException as error:
                    self.to_stdout = True
                    print_entry({
                        'method': 'warn',
                        'message': f'monday-code logs not reachable ({error}) - logging to stdout',
                        'payload': {'logger': 'monday_logging'},
                    })
            print_entry(entry)


def print_entry(entry):
    """One JSON line per record, for local runs and as the fallback."""
    line = {'level': entry['method'], 'message': entry['message'], 'payload': entry['payload']}
    if entry.get('error'):
        line['error'] = entry['error']
    stream = sys.stderr if entry['method'] == 'error' else sys.stdout
    print(json.dumps(line, ensure_ascii=False, default=str), file=stream, flush=True)


def setup_logging(level=logging.INFO):
    """Routes every logger in the process - every feature, the server - through one handler."""
    root = logging.getLogger()
    # Replaces whatever was installed before (logging.basicConfig()), so no line is written twice.
    root.handlers[:] = [MondayCodeLogHandler()]
    root.setLevel(level)

    # The HTTP clients log every request at INFO; the features log what matters.
    for name in ('httpx', 'httpcore', 'urllib3'):
        logging.getLogger(name).setLevel(logging.WARNING)


class RequestLogMiddleware:
    """
    Logs every request once it is answered:

      POST /customer-name-split -> customer_name_split 200 (180 ms)

    with the board, item, request id and the verified token's non-secret claims
    in the payload. The feature is the one whose route answered (set by its
    router's dependency), never something the payload names.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        # The body is read here so the log can name the board and item, then
        # handed on to the route unchanged.
        body = await read_body(receive)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        status = 500

        async def send_and_record(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            await send(message)

        state = scope.setdefault('state', {})
        token = request_context.set({'request_id': uuid.uuid4().hex[:12]})
        started = time.monotonic()
        try:
            await self.app(scope, replay, send_and_record)
        finally:
            log_request(scope['method'], scope['path'], state, status, time.monotonic() - started, body)
            request_context.reset(token)


async def read_body(receive):
    chunks = []
    while True:
        message = await receive()
        if message['type'] != 'http.request':
            break
        chunks.append(message.get('body', b''))
        if not message.get('more_body'):
            break
    return b''.join(chunks)


def log_request(method, path, state, status, seconds, body):
    """`POST / -> company_enrichment 200 (12 ms)`, with the board and item in the payload."""
    routed_to = state.get('feature')
    if routed_to is None:
        routed_to = 'health check' if path in ('/', '/health') and method in ('GET', 'HEAD') else 'no app'

    if status >= 500:
        level = logging.ERROR
    elif status >= 400:
        level = logging.WARNING
    elif routed_to == 'health check':
        level = logging.DEBUG  # monday checks every few seconds; not worth a line each
    else:
        level = logging.INFO

    duration_ms = round(seconds * 1000)
    payload = {
        'method': method,
        'path': path,
        'routed_to': routed_to,
        'status': status,
        'duration_ms': duration_ms,
        **block_ids(body),
    }
    if state.get('monday_claims'):
        payload['jwt'] = state['monday_claims']
        payload['aud_check'] = state.get('monday_aud_check')
    log.log(level, f'{method} {path} -> {routed_to} {status} ({duration_ms} ms)', extra={'payload': payload})


def block_ids(body):
    """boardId / itemId (and monday's actionUuid) from a block call's body, as the features read them."""
    try:
        data = json.loads(body or b'{}')
    except ValueError:
        return {}

    payload = data.get('payload') if isinstance(data, dict) else None
    payload = payload if isinstance(payload, dict) else {}
    ids = {}

    metadata = (data.get('runtimeMetadata') if isinstance(data, dict) else None) or payload.get('runtimeMetadata')
    if isinstance(metadata, dict) and metadata.get('actionUuid'):
        ids['action_uuid'] = str(metadata['actionUuid'])

    fields = payload.get('inputFields') or payload.get('inboundFieldValues') or {}
    if not isinstance(fields, dict):
        return ids

    for key, name in (('boardId', 'board_id'), ('itemId', 'item_id')):
        value = fields.get(key)
        if isinstance(value, dict):
            value = value.get('value') or value.get('id')
        if value not in (None, ''):
            ids[name] = str(value)
    return ids
