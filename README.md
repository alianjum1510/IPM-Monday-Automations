# monday automations — one FastAPI app, one deployment

The automation blocks of one monday.com app, served by **one FastAPI
application** on **one monday-code deployment**. The route a block calls
decides which feature runs.

```
main.py                         create_app(): FastAPI app, startup settings check, request log, routers
Procfile                        web: uvicorn main:app  (what monday-code runs)
.mondaycoderc                   Python 3.12
requirements.txt                the one dependency list (FastAPI only - no Flask)
pytest.ini                      runs every test under app/

app/
  core/                         shared by every feature, knows none of them
    config.py                   settings: process env first, then the monday-code service
    security.py                 the monday JWT check: signature, exp, aud (per route)
    logging.py                  Logs-page handler, request_id/feature on every line, request log
    blocks.py                   block input helpers, monday's error format
    features.py                 Feature + feature_router(): what every feature route runs
    testing.py                  monday JWTs for tests
  api/
    router.py                   FEATURES = [...]: one line per feature
    health.py                   GET/HEAD / and /health
  features/
    company_enrichment/         Company Enrichment block - see its README.md
    customer_name_split/        Split Customer Name block - see its README.md
  tests/                        routing, authentication, config, logging, integration, independence
```

## Routes

| Method + path | Feature | Auth |
| --- | --- | --- |
| `POST /` | Company Enrichment (the block's URL from before the merge) | monday JWT |
| `POST /company-enrichment` (and `/company-enrichment/`) | Company Enrichment | monday JWT |
| `POST /customer-name-split` (and `/customer-name-split/`) | Customer Name Split | monday JWT |
| `POST /monday/split-name` | Customer Name Split (the old app's URL) | monday JWT |
| `GET` / `HEAD` `/` and `/health` | health check (`OK`) | none |
| anything else | 404 | — |

In the Developer Center, each block's **Deployment** section connects this
app's monday-code deployment and sets the block's **sub-route** (Company
Enrichment: empty or `/company-enrichment`; Customer Name Split:
`/customer-name-split`). Do not paste a Version URL into a block — it belongs
to one version only.

## Settings

Set on the app in the Developer Center (Server-side code → Environment variables / Secrets).
Startup logs, per feature, `Config OK (<feature>)` or
`Missing environment variables (<feature>): …`, and which source each key
came from (`env` or `monday-code`) — names only, never values.

| Key | Required by | Notes |
| --- | --- | --- |
| `MONDAY_SIGNING_SECRET` | every route | the Signing Secret of **this** app |
| `MONDAY_JWT_AUDIENCE_BASE_URLS` | every route (enforce mode) | comma-separated deployment base URLs a token's `aud` may name, e.g. the **Live URL** and the draft **Version URL** |
| `MONDAY_JWT_AUDIENCE_MODE` | optional | `enforce` (default) or `report` — report logs an `aud` mismatch and lets it through; for measuring on a draft only |
| `MONDAY_API_TOKEN` | both features | `MONDAY_API_KEY` also works |
| `OPENAI_API_KEY` | company_enrichment | also `OPENAI_MODEL`, `OPENAI_TIMEOUT_MS`, `DEFAULT_BOARD_ID`, `BOARD_ITEM_DELAY_MS`, … (see `app/features/company_enrichment/config/env.py`) |
| `MONDAY_API_VERSION` | optional | if set, both features use it (defaults: enrichment `2024-10`, name split `2025-04`) |
| `PORT` | server | set by monday-code |

A request to a feature whose required setting is missing gets monday's error
format (`severityCode` 4000), so monday does not retry it for 30 minutes.

## Authentication

Every feature route checks monday's JWT (`app/core/security.py`): HS256
signature with `MONDAY_SIGNING_SECRET`, `exp` present and not expired, and
`aud` equal to one of `MONDAY_JWT_AUDIENCE_BASE_URLS` + the path the request
came in on. A token for one block's route is therefore rejected on another's.
The request log records the verified `aud`, `exp`, `iat` and `accountId` —
never the token or its `shortLivedToken`.

## Logs

Every line goes to the Developer Center's **Logs** page with its fields in the
**payload** column, including `request_id` and `feature`, so one run — the
enrichment's background thread included — can be followed end to end.

One line per request says which feature answered it — read this first when an
automation fails:

```
POST / -> company_enrichment 200 (4 ms)            payload: routed_to, status, board_id, item_id, jwt, aud_check
POST /customer-name-split -> customer_name_split 200 (180 ms)
```

Health checks are not logged. If the Logs page shows nothing after a deploy,
set `LOG_TARGET=stdout` to log plain JSON lines to the console instead.

## Run, test, deploy

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                               # every test
.venv/bin/uvicorn main:app --port 8080         # every feature on :8080

npx @mondaycom/apps-cli code:push -i <APP_VERSION_ID> -d .
```

Before `code:push`, move `.venv/`, `*.tar.gz` and spreadsheets out of the folder.

## Adding an automation

1. Create `app/features/<name>/` with `router.py`, `service.py`, `schemas.py` and `tests/`.
2. Put the logic in `service.py`, using `app/core` for settings and logging.
3. In `router.py`: `router = feature_router('<name>', REQUIRED_SETTINGS)`, a route at
   `/<name>` (and `/<name>/`), and `FEATURE = Feature(...)`. The JWT check and the
   settings check come with `feature_router`.
4. Add `FEATURE` to `FEATURES` in `app/api/router.py`.
5. Tests: the feature's own, plus a routing and an auth case (`app/core/testing.py`
   mints the tokens). Every existing suite must still pass.
6. In the Developer Center: a new **Automation block** feature in this app, connected
   to the same deployment, sub-route `/<name>`.
7. Add only the settings the feature needs; deploy to a draft, check its request line
   in Logs, promote.

A feature imports nothing from another feature
(`app/tests/test_independence.py`), so one can later be lifted into its own
deployment without touching the others.
