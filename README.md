# monday automations — one FastAPI app, one deployment

The features of one monday.com app - five automation blocks and one item
view - served by **one FastAPI application** on **one monday-code
deployment**. The route a feature calls decides which feature runs.

```
main.py                         create_app(): FastAPI app, startup settings check, request log, routers
Procfile                        web: uvicorn main:app  (what monday-code runs)
.mondaycoderc                   Python 3.12
requirements.txt                the one dependency list (FastAPI only - no Flask)
pytest.ini                      runs every test under app/

app/
  core/                         shared by every feature, knows none of them
    config.py                   settings: process env first, then the monday-code service
    security.py                 the block JWT check (signature, exp, aud per route) and the view session-token check
    views.py                    a View feature's error format: {"error": ...}
    logging.py                  Logs-page handler, request_id/feature on every line, request log
    blocks.py                   block input helpers, monday's error format
    features.py                 Feature + feature_router(): what every feature route runs
    name_split.py               the name split rule (100 chars, cut at a word) - every feature that splits a name
    monday_client.py            async monday GraphQL client: read columns, write in one mutation
    testing.py                  monday JWTs and session tokens for tests
  api/
    router.py                   FEATURES = [...]: one line per feature
    health.py                   GET/HEAD / and /health
  features/
    company_enrichment/         Company Enrichment block - see its README.md
    customer_name_split/        Customer Name Split block (Kunden, Warm Lead) - see its README.md
    vendor_name_split/          Vendor Name Split block (Vendors board) - see its README.md
    address_validator/          Fill address + Validate address blocks (HERE, Address Master boards) - see its README.md
    comment_builder/            Comment Builder item view (page + AI helpers) - see its README.md
  tests/                        routing, authentication, config, logging, integration, independence
```

## Routes

| Method + path | Feature | Auth |
| --- | --- | --- |
| `POST /` | Company Enrichment (the block's URL from before the merge) | monday JWT |
| `POST /company-enrichment` (and `/company-enrichment/`) | Company Enrichment | monday JWT |
| `POST /customer-name-split` (and `/customer-name-split/`) | Customer Name Split | monday JWT |
| `POST /monday/split-name` | Customer Name Split (the old app's URL) | monday JWT |
| `POST /vendor-name-split` (and `/vendor-name-split/`) | Vendor Name Split | monday JWT |
| `POST /address-validator/fill` (and `/fill/`) | Address Validator — Fill address (mode `address`) | monday JWT |
| `POST /address-validator/validate` (and `/validate/`) | Address Validator — Validate address (mode `fields`) | monday JWT |
| `POST /address-validator` (and `/address-validator/`) | Address Validator — auto mode (the old app's `/action`) | monday JWT |
| `GET` `/comment-builder` (and sub-paths), `/assets/*` | Comment Builder page | none (monday's iframe) |
| `POST /api/ai/write`, `/api/ai/summarize`, `/api/ai/autofill` | Comment Builder AI | monday session token |
| `GET /comment-builder/health` | Comment Builder diagnostics | none |
| `GET` / `HEAD` `/` and `/health` | health check (`OK`) | none |
| anything else | 404 | — |

In the Developer Center, each block's **Execution URL** is the deployment URL
plus the block's own path: `/company-enrichment`, `/customer-name-split`,
`/vendor-name-split`, `/address-validator/fill`, `/address-validator/validate`. The URL belongs to one app version, so check the blocks'
Execution URLs whenever a new version is created. The **Comment Builder** item
view is deployed on monday code with the route `/comment-builder`.

## Settings

Set on the app in the Developer Center (Server-side code → Environment variables / Secrets).
Startup logs, per feature, `Config OK (<feature>)` or
`Missing environment variables (<feature>): …`, and which source each key
came from (`env` or `monday-code`) — names only, never values.

| Key | Required by | Notes |
| --- | --- | --- |
| `MONDAY_SIGNING_SECRET` | every block route | the Signing Secret of **this** app |
| `MONDAY_CLIENT_SECRET` | comment_builder | the **Client Secret** of this app (Basic Information) — signs the item view's session token; not the Signing Secret |
| `MONDAY_JWT_AUDIENCE_BASE_URLS` | every block route (enforce mode) | comma-separated deployment base URLs a token's `aud` may name, e.g. the **Live URL** and the draft **Version URL** |
| `MONDAY_JWT_AUDIENCE_MODE` | optional | `enforce` (default) or `report` — report logs an `aud` mismatch and lets it through; for measuring on a draft only |
| `MONDAY_API_TOKEN` | the name splits and enrichment | `MONDAY_API_KEY` also works; address_validator falls back to the verified JWT's `shortLivedToken` |
| `HERE_API_KEY` | address_validator | also reads `ADDRESS_COLUMN_LOCATION_ID` and other `ADDRESS_*` overrides (see its README) |
| `OPENAI_API_KEY` | company_enrichment, comment_builder | enrichment also reads `OPENAI_MODEL`, `OPENAI_TIMEOUT_MS`, `DEFAULT_BOARD_ID`, `BOARD_ITEM_DELAY_MS`, … (see `app/features/company_enrichment/config/env.py`) |
| `COMMENT_BUILDER_OPENAI_MODEL` | optional | Comment Builder's model (default `gpt-4o-mini`); `OPENAI_MODEL` is enrichment's only |
| `MONDAY_APP_ID` | optional | the app id the item view's session token must name (default `11727119`) |
| `MONDAY_API_VERSION` | optional | if set, both features use it (defaults: enrichment `2024-10`, name split `2025-04`) |
| `PORT` | server | set by monday-code |

A request to a block whose required setting is missing gets monday's error
format (`severityCode` 4000), so monday does not retry it for 30 minutes. The
item view answers `{"error": ...}` instead, which its page shows.

## Authentication

Every block route checks monday's JWT (`app/core/security.py`): HS256
signature with `MONDAY_SIGNING_SECRET`, `exp` present and not expired, and
`aud` equal to one of `MONDAY_JWT_AUDIENCE_BASE_URLS` + the path the request
came in on. A token for one block's route is therefore rejected on another's.
The request log records the verified `aud`, `exp`, `iat` and `accountId` —
never the token or its `shortLivedToken`.

The item view's page is public (monday's iframe loads it with no header); its
`/api/ai/*` calls carry monday's **session token**, checked by
`verify_session_token`: HS256 with `MONDAY_CLIENT_SECRET`, `exp`, and
`dat.app_id` = this app. A block's JWT does not open the AI routes, and a session
token does not open a block. The log records the token's `user_id`,
`account_id`, `app_id` and `exp`.

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

Health checks and the item view's page and asset loads are not logged at INFO. If the Logs page shows nothing after a deploy,
set `LOG_TARGET=stdout` to log plain JSON lines to the console instead.

## Run, test, deploy

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                               # every test
.venv/bin/uvicorn main:app --port 8080         # every feature on :8080

npx @mondaycom/apps-cli code:push -i <APP_VERSION_ID> -d .
```

Before `code:push`, move `.venv/`, `*.tar.gz`, `*.zip` and spreadsheets out of the folder
(`code:push` uploads the folder as it is; `.gitignore` does not apply).

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

A **View** feature (item view, board view, widget) differs in steps 3 and 6, as
`comment_builder` shows: `router = view_router('<name>')`, the page at `/<name>`
with no auth, each API route with `dependencies=view_api('<name>', REQUIRED_SETTINGS)`
(the session-token check), and `Feature(..., auth='session')`. In the Developer
Center it is a View feature deployed on monday code with the route `/<name>`.

A feature imports nothing from another feature
(`app/tests/test_independence.py`), so one can later be lifted into its own
deployment without touching the others.
