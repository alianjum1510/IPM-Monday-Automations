"""
One monday-code server for two apps, each kept unchanged in its own folder:

  company_enrichment/       "Company Enrichment" block    POST /company-enrichment
  customer_name_split_py/   "Split Customer Name" block   POST /customer-name-split
                                                          (or its pre-merge URLs: POST /, /monday/split-name)

monday-code gives an app one port (PORT, 8080), so both apps are mounted on
this one server, each under its own path. GET / answers monday's health check.

This file is the only code the two apps share.
"""
import os
import sys
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

# Every setting company_enrichment reads (company_enrichment/src/config/env.py
# and src/lib/taxonomy.py). PORT is left out: monday-code sets it directly.
COMPANY_ENRICHMENT_SETTINGS = [
    'MONDAY_API_TOKEN', 'MONDAY_API_KEY', 'MONDAY_API_VERSION',
    'OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_COUNTRY_MODEL', 'OPENAI_TIMEOUT_MS',
    'FX_RATES_URL', 'FX_FALLBACK_URL', 'FX_TTL_MS',
    'DEFAULT_BOARD_ID', 'BOARD_ITEM_DELAY_MS', 'LIFECYCLE_STAGE_SOURCES', 'TAXONOMY_TTL_MS',
]


def log(message):
    print(message, flush=True)


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
        log(f'monday-code settings not read ({error}) - using the process environment only')


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
        print(f"Missing environment variables: {', '.join(missing)}", file=sys.stderr, flush=True)
    await check_customer_name_split_config()

    log(f'Company Enrichment running on port {env.port}')
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

# The URLs the customer name split app answered before the merge: its block's
# Execution URL was the bare Version URL, or that plus /monday/split-name. A
# block or a queued monday retry still on one of them reaches the name split
# instead of a 405. The enrichment block uses /company-enrichment.
CUSTOMER_NAME_SPLIT_OLD_PATHS = {'/', '/monday/split-name'}


async def app(scope, receive, send):
    """
    The server. A block URL ending on the bare mount ("…/company-enrichment",
    no trailing slash) is handed to that app as "…/company-enrichment/" - the
    router would otherwise answer it with a redirect, and a POST from monday
    is not guaranteed to follow one.
    """
    if scope['type'] == 'http':
        path = scope['path']
        if path in MOUNTS:
            path += '/'
        elif scope['method'] == 'POST' and path in CUSTOMER_NAME_SPLIT_OLD_PATHS:
            path = '/customer-name-split' + path
        scope = {**scope, 'path': path, 'raw_path': path.encode()}
    await api(scope, receive, send)
