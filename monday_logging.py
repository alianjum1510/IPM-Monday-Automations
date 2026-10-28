"""
Structured logs for the Developer Center's Logs page.

Both apps log through Python's `logging` as usual. This sends every record to
the monday-code service's /logs endpoint, which shows it on the Logs page with
its fields in the "payload" column (a plain print() arrives with payload null):

  log.info('Item 42: updated 21 columns', extra={'payload': {'item_id': '42', 'columns_written': 21}})

Sending happens on a background thread, so a log call never waits on the
network - not in a request, not in an enrichment run.

Off monday-code (local runs, tests) the service is not there: the first failed
send switches to stdout, one JSON line per record. LOG_TARGET=stdout forces
that on monday-code too, should the Logs page not show the records.
"""
import json
import logging
import os
import queue
import sys
import threading
import traceback

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


def to_entry(record):
    """A log record as monday-code's /logs takes it: message, method (level), payload, error."""
    entry = {
        'method': LEVELS.get(record.levelno, 'info'),
        'message': record.getMessage(),
        'payload': {'logger': record.name, **(getattr(record, 'payload', None) or {})},
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
    """Routes every logger in the process - both apps, the server - through one handler."""
    root = logging.getLogger()
    # Replaces what an app's own logging.basicConfig() installed, so no line is written twice.
    root.handlers[:] = [MondayCodeLogHandler()]
    root.setLevel(level)

    # The HTTP clients log every request at INFO; the apps log what matters.
    for name in ('httpx', 'httpcore', 'urllib3'):
        logging.getLogger(name).setLevel(logging.WARNING)
