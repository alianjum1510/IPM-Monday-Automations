"""
One monday-code server for two apps, each kept unchanged in its own folder:

  company_enrichment/       "Company Enrichment" block    POST /company-enrichment  (or POST /, as before the merge)
  customer_name_split_py/   "Split Customer Name" block   POST /customer-name-split (or /monday/split-name)

monday-code gives an app one port (PORT, 8080), so both apps are mounted on
this one server, each under its own path. GET / answers monday's health check.

Every request is logged once - which app it went to, the board and item, the
status and how long it took - so the Logs page shows what each automation
run actually reached.

This file and monday_logging.py are the only code the two apps share.
"""
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Each app imports its own code the way it does when run on its own
# (`src.…` for the enrichment, `app.…` for the name split), so both folders
# go on the import path and neither app needs a change.
sys.path[:0] = [str(ROOT / 'company_enrichment'), str(ROOT / 'customer_name_split_py')]

from a2wsgi import WSGIMiddleware  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402

from app.config import assert_configured as check_customer_name_split_config  # noqa: E402
from app.main import app as customer_name_split  # noqa: E402
from monday_logging import setup_logging  # noqa: E402

# After the imports above: it replaces the logging setup the name split installs on import.
setup_logging()
log = logging.getLogger('monday_apps')

# Every setting company_enrichment reads (company_enrichment/src/config/env.py
# and src/lib/taxonomy.py). PORT is left out: monday-code sets it directly.
COMPANY_ENRICHMENT_SETTINGS = [
    'MONDAY_API_TOKEN', 'MONDAY_API_KEY', 'MONDAY_API_VERSION',
    'OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_COUNTRY_MODEL', 'OPENAI_TIMEOUT_MS',
    'FX_RATES_URL', 'FX_FALLBACK_URL', 'FX_TTL_MS',
    'DEFAULT_BOARD_ID', 'BOARD_ITEM_DELAY_MS', 'LIFECYCLE_STAGE_SOURCES', 'TAXONOMY_TTL_MS',
]


async def copy_monday_code_settings(keys):
    """
    Copies Developer Center settings that are not in os.environ into it.

    company_enrichment reads its settings from os.environ, but on monday-code the
    Developer Center's Environment variables and Secrets are served by the
    monday-code service (see customer_name_split_py/app/config.py). A value
    already in os.environ wins. Off monday-code (local runs, tests) the service
    is not there, and this logs one line and changes nothing.
    """
    missing = [key for key in keys if not os.environ.get(key)]
    if not missing:
        return

    try:
        import monday_code
        from monday_code.exceptions import NotFoundException

        async with monday_code.ApiClient(monday_code.Configuration()) as client:
            readers = [
                monday_code.SecretsApi(client).get_secret,
                monday_code.EnvironmentVariablesApi(client).get_environment_variable,
            ]
            for key in missing:
                for read in readers:
                    try:
                        value = await read(key)
                    except NotFoundException:
                        continue
                    if value is not None:
                        os.environ[key] = str(value)
                        break
    except Exception as error:  # noqa: BLE001 - not on monday-code, or the service is down
        log.warning(f'monday-code settings not read ({error}) - using the process environment only')


company_enrichment = None  # the Flask app in company_enrichment/index.py, loaded at startup


def company_enrichment_wsgi(environ, start_response):
    return company_enrichment(environ, start_response)


@asynccontextmanager
async def lifespan(_):
    global company_enrichment

    # company_enrichment reads its settings once, on import, so they are put in
    # place first and the app is imported after.
    await copy_monday_code_settings(COMPANY_ENRICHMENT_SETTINGS)
    import index
    from src.config.env import assert_configured, env

    company_enrichment = index.app

    # The startup lines each app logs when it runs on its own.
    missing = assert_configured()
    if missing:
        log.error(f"Missing environment variables: {', '.join(missing)}", extra={'payload': {'missing': missing}})
    await check_customer_name_split_config()

    log.info(
        f'Company Enrichment running on port {env.port}',
        extra={'payload': {'port': env.port, 'apps': list(APPS.values())}},
    )
    yield


api = FastAPI(title='monday apps', lifespan=lifespan)


# HEAD too: monday's health checker uses it.
@api.api_route('/', methods=['GET', 'HEAD'], response_class=PlainTextResponse)
@api.api_route('/health', methods=['GET', 'HEAD'], response_class=PlainTextResponse)
def health():
    return 'OK'


api.mount('/company-enrichment', WSGIMiddleware(company_enrichment_wsgi))
api.mount('/customer-name-split', customer_name_split)

MOUNTS = {'/company-enrichment', '/customer-name-split'}

# The URLs each app answered before the merge. This monday app is Company
# Enrichment's, and its block's Execution URL is the bare Version URL - so a
# POST to "/" is the enrichment block and stays the enrichment. The name split
# came from another app; its /monday/split-name URL is kept for a block set up
# the way its old README said.
OLD_PATHS = {
    '/': '/company-enrichment/',
    '/monday/split-name': '/customer-name-split/monday/split-name',
}


# Mount -> app name, for the request log.
APPS = {'/company-enrichment': 'company_enrichment', '/customer-name-split': 'customer_name_split'}


async def app(scope, receive, send):
    """
    The server: picks the app for the path, and logs the request once it is answered.

    A block URL ending on the bare mount ("…/company-enrichment", no trailing
    slash) is handed to that app as "…/company-enrichment/" - the router would
    otherwise answer it with a redirect, and a POST from monday is not
    guaranteed to follow one.
    """
    if scope['type'] != 'http':
        await api(scope, receive, send)
        return

    requested = scope['path']
    path = requested
    if path in MOUNTS:
        path += '/'
    elif scope['method'] == 'POST' and path in OLD_PATHS:
        path = OLD_PATHS[path]
    scope = {**scope, 'path': path, 'raw_path': path.encode()}

    # The body is read here so the log can name the board and item, then
    # handed on to the app unchanged.
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

    started = time.monotonic()
    try:
        await api(scope, replay, send_and_record)
    finally:
        log_request(scope['method'], requested, path, status, time.monotonic() - started, body)


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


def log_request(method, requested, path, status, seconds, body):
    """`POST / -> company_enrichment 200 (12 ms)`, with the board and item in the payload."""
    routed_to = next((name for prefix, name in APPS.items() if path.startswith(prefix)), None)
    if routed_to is None:
        routed_to = 'health check' if path in ('/', '/health') else 'no app'

    if status >= 500:
        level = logging.ERROR
    elif status >= 400:
        level = logging.WARNING
    elif routed_to == 'health check':
        level = logging.DEBUG  # monday checks every few seconds; not worth a line each
    else:
        level = logging.INFO

    duration_ms = round(seconds * 1000)
    log.log(
        level,
        f'{method} {requested} -> {routed_to} {status} ({duration_ms} ms)',
        extra={'payload': {
            'method': method,
            'path': requested,
            'routed_to': routed_to,
            'status': status,
            'duration_ms': duration_ms,
            **block_ids(body),
        }},
    )


def block_ids(body):
    """boardId / itemId from a block call's body, as both apps read them."""
    try:
        data = json.loads(body or b'{}')
    except ValueError:
        return {}

    payload = data.get('payload') if isinstance(data, dict) else None
    payload = payload if isinstance(payload, dict) else {}
    fields = payload.get('inputFields') or payload.get('inboundFieldValues') or {}
    if not isinstance(fields, dict):
        return {}

    ids = {}
    for key, name in (('boardId', 'board_id'), ('itemId', 'item_id')):
        value = fields.get(key)
        if isinstance(value, dict):
            value = value.get('value') or value.get('id')
        if value not in (None, ''):
            ids[name] = str(value)
    return ids
