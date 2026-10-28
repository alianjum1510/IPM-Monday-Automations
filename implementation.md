# Implementation Plan — FastAPI-only monday.com Automation Platform

Source of truth: [`Claude.MD`](Claude.MD). This document is the plan to verify **before** any code changes.
Nothing described here has been implemented yet.

- Branch: `merge-customer-company-app`, HEAD `8698ad8 Working Company Enrichment merged`
- Status: plan only — waiting for an explicit "implement" instruction

---

## 1. Summary

**Goal:** Company Enrichment and Customer Name Split run in **one FastAPI application**, inside **one
monday.com app**, on **one monday-code deployment**. The layout must make adding a third automation a
matter of adding a folder, a router line, tests and a monday block.

**What does not change:** enrichment research, prompts, parsing, column mapping, revenue banding, stage
guard, retry logic, log messages; name-split rules (last space at or before 100 chars), board ids, column
ids, write-only-what-changed behaviour.

**What changes:** the HTTP layer only — Flask and the `a2wsgi` bridge are removed, both features become
FastAPI routers in a modular `app/` package, and shared pieces (config, authentication, logging) move to
`app/core/`.

### Baseline (verified, read-only)

| Check | Result |
| --- | --- |
| Working tree vs `8698ad8` | identical (only `Claude.MD` untracked) |
| Test suite (Python 3.12) | **139 passed** — root 21, `company_enrichment/test` 83, `customer_name_split_py/tests` 35 |
| Flask usage | only `company_enrichment/index.py` (+ `a2wsgi` mount in `main.py`) |
| Business logic Flask-free | yes — `company_enrichment/src/**` never imports Flask |
| Name split framework | already FastAPI (`customer_name_split_py/app/main.py` builds its own `FastAPI()` app) |

### Decisions

| # | Decision | Why |
| --- | --- | --- |
| D1 | Layout = the `Claude.MD` tree (`app/core`, `app/api`, `app/features/…`) | chosen by the user; real Python packages, no `sys.path` workaround |
| D2 | **Two action blocks** in one app (Company Enrichment, Customer Name Split), one deployment, one path each | independently selectable/testable automations; path selects the feature (see §2) |
| D3 | Not one block per board, not one block with a "feature" input | `Claude.MD` §4/§6: no payload-chosen handlers, reuse blocks across boards |
| D4 | No shared monday API client yet | the two clients behave differently (see §3.3); merging risks regressions |
| D5 | Async / callback execution, durable runs and duplicate-work prevention are a **separate reliability phase** | `Claude.MD` §9: keep reliability work apart from the framework refactor |
| D6 | **Full JWT validation** — signature, `exp` and `aud` — required before production; `verify_aud=False` is not kept | monday's docs require all three (§2.2); see §3.4 |
| D7 | **Git tags are the release checkpoints**; monday app versions are deployment artifacts, not code history | rollback = re-deploy a known-good tag (§9) |

### Review feedback incorporated

| Priority | Finding | Position in this plan |
| --- | --- | --- |
| High | JWT validation | signature, `exp` and expected `aud` validated per feature route; staged rollout in §3.4 |
| High | Git-based rollback | known-good tags and recovery steps defined and rehearsed (§9) |
| Medium | Configuration consistency | required settings checked per feature at startup, platform settings documented, secrets never logged (§3.5) |
| Medium | Background execution | kept as-is for the refactor; durable execution and duplicate-work prevention in the reliability phase (§8) |
| Medium | Modular architecture | single FastAPI deployment with separate feature routers, services, schemas and tests (§3, §10) |

Verdict recorded: architecture and Git-based rollback approved, **subject to** correct JWT audience
validation and a tested deployment and recovery process.

---

## 2. monday.com research findings

### 2.1 Verified

| Topic | Finding | Source |
| --- | --- | --- |
| Python runtime | monday-code supports Python 3.10.x, 3.11.x, 3.12.x; set in `.mondaycoderc` | [monday code runtimes](https://developer.monday.com/apps/docs/monday-code-runtimes) |
| Deploying | server-side code "can only be deployed using the CLI" (`mapps code:push -i <version id>`) | [Deploy your app](https://developer.monday.com/apps/docs/deploy-your-app) |
| Versions | "Code deployments only impact the selected draft version" | [Deploy your app](https://developer.monday.com/apps/docs/deploy-your-app) |
| Per-feature route | the Feature Deployment flow asks for "the subroute of the feature" — a feature is pointed at a **subroute** of the deployment, not only at its root | [Deploy your app](https://developer.monday.com/apps/docs/deploy-your-app) |
| Settings service | the monday-code SDK reads Secrets and Environment variables from a local service at `http://localhost:59999` | `monday-code` SDK 2.1.0 (`configuration.py`, `secrets_api.py`, `environment_variables_api.py`) |
| Structured logs | `POST http://localhost:59999/logs` with `message`, `method` (level) and `payload` fills the Logs page **payload** column | SDK `logs_api.py`; confirmed live in the app's Logs page (payload column populated) |
| Live routing today | every block call arrives as `POST /` → routed to Company Enrichment; **no request has ever reached `/customer-name-split`** | app Logs page, 28/10/2026 |

### 2.2 From the official developer docs

**Block types**
- Current: **Automation block** and **Field for automation block** (monday workflows) —
  [monday workflows](https://developer.monday.com/apps/docs/monday-workflows).
- Legacy **Integration for sentence builder** is discontinued: "all apps using the legacy *Integration for
  sentence builder* feature must migrate to *Automation block* app features before April 30th, 2026" —
  [migration overview](https://developer.monday.com/apps/docs/automation-features-migration-overview).
  Both blocks must therefore be Automation block features.

**One feature per block**
- "Each block and field lives in a separate app feature." —
  [Create an automation block](https://developer.monday.com/apps/docs/create-an-automation-block).
  No per-app block limit is documented; the only related limit is "up to 10 private apps" on monday code —
  [quotas and limits](https://developer.monday.com/apps/docs/quotas-and-limits).
- Nothing found that forces separate apps or deployments for two blocks.

**How a block reaches the deployment — the sub-route**
- A block has a **Deployment** section ("Connect a deployment to populate the block") and an
  **API configuration** section ("Actions: Execution URL") —
  [Create an automation block](https://developer.monday.com/apps/docs/create-an-automation-block).
- "Your monday code URL is automatically connected, and you can choose an **optional sub-route** to serve
  your feature." — [Get started](https://developer.monday.com/apps/docs/get-started).
- Feature Deployment widget: "Provide the subroute of the feature to render." —
  [Deploy your app](https://developer.monday.com/apps/docs/deploy-your-app).
- CLI equivalent: `mapps app-features:build -a <appId> -i <versionId> -d <featureId> -t monday_code -u /<path>` —
  [CLI reference](https://developer.monday.com/apps/docs/command-line-interface-cli).
- **Version URL** "updates each time you create a new version"; the **Live URL** is static —
  [Manage monday code](https://developer.monday.com/apps/docs/manage-monday-code-in-the-developer-center).
  A pasted Version URL can therefore point at an older version's deployment.

**Versions**
- "no live features are affected until promoted"; the **active** version "is visible only to the
  collaborator who designated it as active" (App Versions → ⋯ → "Set as active for me") —
  [App versioning](https://developer.monday.com/apps/docs/app-versioning).
- To test blocks, "Ensure the version containing the blocks… is set as the active version" —
  [Test your blocks](https://developer.monday.com/apps/docs/test-your-blocks).

**Request and authentication**
- monday POSTs to the block's URL with an authorization JWT; body `payload.{blockKind, inputFields,
  inboundFieldValues, recipeId, integrationId, credentialsValues}` + `runtimeMetadata` —
  [Workflow actions](https://developer.monday.com/apps/docs/workflows-actions).
  **No field identifies which block is running** → the path is the only reliable way to tell blocks apart.
- The JWT is "signed by your app's *Signing Secret*"; claims `accountId`, `userId`, `aud` ("the app's
  endpoint URL"), `exp`, `shortLivedToken`. The docs say to "Check that the `aud` field matches your
  integration app's endpoint. Verify the `exp` field." —
  [Authorization header](https://developer.monday.com/apps/docs/authorization-header).
  The official Python quickstart skips the `aud` check, and a community report shows `aud` carrying a
  draft URL on live apps. That is a reason to **measure** the real `aud` values, not to skip the check:
  this plan validates `aud` (§3.4).

**Retries, timeouts, async**
- "If your server responds with any other status [than 200], or doesn't respond within a minute, the monday
  platform will retry the request for 30 minutes" — [Workflow actions](https://developer.monday.com/apps/docs/workflows-actions);
  4xx and severity-code responses are not retried — [Error handling](https://developer.monday.com/apps/docs/error-handling).
- monday-code request timeout: 300 seconds — [quotas and limits](https://developer.monday.com/apps/docs/quotas-and-limits).
- Async: "Mark block as async"; ack with 200, then POST the result to `payload.callbackUrl` with a JWT signed by
  the signing secret including `appId`; body `{"success": true, "outputFields": {}}` or
  `{"success": false, "severityCode": 4000, …}` —
  [Asynchronous action blocks](https://developer.monday.com/apps/docs/asynchronously-run-your-action-blocks).
- Error format: 4xx/5xx with `severityCode` (4000 = run fails, 6000 = automation disabled),
  `notificationErrorTitle`, `notificationErrorDescription`, `runtimeErrorDescription` —
  [Error handling](https://developer.monday.com/apps/docs/error-handling).

**Settings on monday-code**
- Python SDK reads Secrets / Environment variables from `http://localhost:59999` —
  [Python SDK](https://developer.monday.com/apps/docs/monday-code-python-sdk). For non-JS languages "you need to
  redeploy the service so new variables will take effect", which suggests injection at deploy time.

### 2.3 Still unverified (not stated in the docs)

1. Whether a typed absolute **Execution URL** is ignored once the block's Deployment is monday code.
2. Whether automations already on a board pick up block changes without being re-created.
3. Whether Environment variables / Secrets also appear in the process environment (`os.environ`) —
   the design keeps both sources and logs which one each key came from.
4. Exact retry interval/attempts, async callback deadline and callback retries.
5. That the Logs page "payload" column comes from `/logs` payload (consistent with what the Logs page shows today).

### 2.4 Conclusion: how many blocks?

**Two** — one per independently selectable automation:

| Block | Route on the shared deployment | Used on |
| --- | --- | --- |
| Company Enrichment (existing) | `/` (compat) or `/company-enrichment` | lead boards, e.g. Warm Lead Mining Board (Copy) |
| Customer Name Split (new in this app) | `/customer-name-split` | Kunden Dev + Sandbox, Warm Lead Mining Board (Copy) |

One block for both would need a payload field to choose the handler, which `Claude.MD` §4 forbids, and
monday sends no field that identifies the block — so the automations could not be told apart or tested
separately.

### 2.5 Diagnosis of the current failure

The Customer Name Split block's calls arrive at `POST /`, which belongs to Company Enrichment. So the
split never runs, and enrichment runs several times for one item (seen: item `3315753724` enriched 4×).

Most likely cause, per §2.2: the path was typed into the **Execution URL**, but a block connected to
monday code is served at the deployment's URL plus the feature's **sub-route** (Deployment section /
Feature Deployment widget). With the sub-route empty, monday calls `/`. Other contributing causes: the
pasted Version URL belongs to one version only, the edit was made on a version that is not the active one,
or the board automation still uses the old block configuration.

Fix (configuration, no code): set the Customer Name Split feature's sub-route to `/customer-name-split`
in the version under test, make that version active, re-create the board automations — see §6.
**A code refactor alone does not fix this** (`Claude.MD` §6).

---

## 3. Target architecture

### 3.1 File tree

```
main.py                         create_app(): FastAPI app, lifespan, middleware, include api_router
requirements.txt                single dependency list (no Flask, no waitress, no a2wsgi)
requirements-dev.txt            + pytest
Procfile                        unchanged: web: uvicorn main:app --host=0.0.0.0 --port=${PORT:-8080} --no-access-log
.mondaycoderc                   unchanged: Python 3.12.0

app/
  core/
    config.py                   settings: process env first, then monday-code service; startup check
    security.py                 verify_monday_request — monday JWT check, one dependency for every feature
    logging.py                  monday-code /logs handler, request-log middleware, correlation id
    blocks.py                   block input helpers (field), monday error format (monday_error), OK
  api/
    router.py                   FEATURE_ROUTERS = [...] → include_router; one line per feature
    health.py                   GET/HEAD /  and  /health
  features/
    company_enrichment/
      router.py                 POST /, /company-enrichment → parse ids → ack → service.start()
      service.py                start(), run_enrichment()  (from company_enrichment/index.py)
      schemas.py                EnrichmentAck (received, boardId, itemId)
      config/ lib/ services/    moved from company_enrichment/src/** — logic unchanged
      tests/                    moved from company_enrichment/test/** (+ boards.json, taxonomy.json)
    customer_name_split/
      router.py                 POST /customer-name-split, /monday/split-name
      service.py                split_item(): board id → processor  (from app/boards/__init__.py)
      schemas.py                response models
      processors/
        kunden.py               unchanged rules + column ids  (from app/boards/kunden.py)
        warm_lead.py            unchanged rules + column ids  (from app/boards/warm_lead.py)
      split.py                  unchanged
      monday.py                 unchanged (feature's own GraphQL client)
      settings.py               MAX_NAME_LENGTH, TEIL2_MAX_LENGTH, API version (from app/config.py)
      tests/                    moved from customer_name_split_py/tests/**
  tests/
    test_routing.py             every route → right feature; independent of board id
    test_authentication.py      missing secret, missing/invalid JWT, on every feature route
    test_integration.py         end-to-end through main.app with mocked monday/OpenAI
    test_logging.py             request line, feature name, correlation id, payload format
```

### 3.2 Where existing code goes

| Today | Target | Change |
| --- | --- | --- |
| `main.py` (sys.path, a2wsgi mount, path rewriting, request log) | `main.py`, `app/api/router.py`, `app/core/logging.py` | split by responsibility; `sys.path` and `a2wsgi` removed |
| `monday_logging.py` | `app/core/logging.py` | moved, unchanged behaviour |
| `main.py::copy_monday_code_settings` + `customer_name_split_py/app/config.py::get_secret` | `app/core/config.py` | one settings reader for both features |
| `customer_name_split_py/app/auth.py::monday_session` | `app/core/security.py::verify_monday_request` | shared by both features |
| `customer_name_split_py/app/block.py` | `app/core/blocks.py` | shared |
| `company_enrichment/index.py` (Flask) | `app/features/company_enrichment/router.py` + `service.py` | Flask removed; same responses, same log lines |
| `company_enrichment/src/**` | `app/features/company_enrichment/{config,lib,services}` | moved; imports updated only |
| `customer_name_split_py/app/main.py` (own FastAPI app) | `app/features/customer_name_split/router.py` | becomes an `APIRouter` |
| `customer_name_split_py/app/boards/*` | `app/features/customer_name_split/processors/*` | moved; logic unchanged |
| per-folder `requirements.txt` | root `requirements.txt` | merged; `flask`, `waitress`, `a2wsgi` dropped |
| `main_test.py`, `monday_logging_test.py` | `app/tests/*` | moved and extended |

All moves use `git mv` so file history is kept.

### 3.3 Design notes

- **Feature registration:** `app/api/router.py` holds `FEATURE_ROUTERS = [company_enrichment.router,
  customer_name_split.router]`. A new feature adds one line — no growing `if/elif` dispatcher.
- **Path selects the feature.** The board id is only used *inside* the name-split feature to choose the
  Kunden or Warm Lead processor. Nothing in the payload can choose which feature runs.
- **Trailing slashes:** both `/company-enrichment` and `/company-enrichment/` (same for split) are
  registered explicitly with `redirect_slashes=False`, so monday never receives a 307 redirect on a POST.
- **Settings at import time:** enrichment currently reads its settings when imported, which is why
  `main.py` imports it late. The `env` object becomes lazy (read on access) and `taxonomy.TTL_MS` becomes
  a function, so import order no longer matters and the late-import trick disappears.
- **Separate monday clients (D4):** enrichment's client (sync `requests`, drops a rejected column and
  retries, `create_labels_if_missing: false`, cursor pagination) and the split's (async `httpx`,
  single write) stay feature-specific. Only the token and API version come from `app/core/config.py`.
- **Correlation id:** the request middleware sets a per-request id (context variable). Every log line
  carries it in its payload, including lines from enrichment's background thread (context copied into the
  thread), so one automation run can be followed end to end.
- **Diagnosable routing:** after the JWT is verified, the request log adds the token's non-sensitive
  claims (`aud`, `exp`, `iat`, `accountId`) to the payload — never the token or `shortLivedToken`.
- **Idempotent handlers:** monday retries failed calls for 30 minutes, so a retried call must be safe.
  The split already writes only what changes; enrichment re-runs are safe but cost an OpenAI call.
- **No new infrastructure:** no database, queue, microservice or new third-party dependency.

### 3.4 Request authentication (JWT)

Every feature route uses one dependency, `app/core/security.py::verify_monday_request`, which rejects a
request unless **all** of these hold:

| Check | Rule | Failure |
| --- | --- | --- |
| Signature | HS256, signed with `MONDAY_SIGNING_SECRET` | 401 |
| Expiry | `exp` present and not in the past (small clock-skew allowance) | 401 |
| Audience | `aud` equals an expected endpoint **for this route** | 401 |
| Secret configured | `MONDAY_SIGNING_SECRET` available | monday error, severity 4000 (no retry storm) |

**Expected audience per route.** The expected value is the deployment base URL plus the route's own path
(e.g. `<base>/customer-name-split` for the split route). Allowed base URLs come from one setting,
`MONDAY_JWT_AUDIENCE_BASE_URLS` (comma-separated: the static **Live URL** and the draft Version URL under
test). The exact comparison rule (trailing slash, sub-route included or not, query string) is fixed from
**measured** claims, not assumed:

1. **Measure (draft only):** deploy with `MONDAY_JWT_AUDIENCE_MODE=report` — signature and `exp` are
   enforced, `aud` mismatches are logged (`aud`, expected values, route) but not rejected. Trigger each
   block once and record the real `aud` values. The full token is never logged.
2. **Fix the rule:** encode the observed format in `verify_monday_request` and its tests (valid, expired,
   wrong signature, wrong audience, audience of the *other* feature's route).
3. **Enforce:** `MONDAY_JWT_AUDIENCE_MODE=enforce` (the default). **Production is only promoted in
   enforce mode**; `report` is a temporary measurement step, never a resting state.

If the measured `aud` turns out not to identify the endpoint (e.g. always a draft host), that is recorded
in §11 as a verified platform limitation with the smallest safe alternative, rather than silently
disabling the check.

### 3.5 Configuration

- One reader in `app/core/config.py`: process environment first, then the monday-code service.
- Each feature declares its **required** settings; at startup every missing one is logged by **name**,
  with the source each present key came from (`env` or `monday-code`). Values, tokens and secrets are
  never logged.
- A request to a feature whose required settings are missing gets monday's error format
  (`severityCode` 4000) instead of an unhandled 500, so monday does not retry it for 30 minutes.

| Setting | Required by | Where it is set |
| --- | --- | --- |
| `MONDAY_API_TOKEN` | both | Developer Center → Server-side code → Environment variables (US) |
| `MONDAY_SIGNING_SECRET` | both (JWT check) | same |
| `MONDAY_JWT_AUDIENCE_BASE_URLS` | both (JWT check) — **new** | same |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_MS` | company_enrichment | same |
| `DEFAULT_BOARD_ID`, `BOARD_ITEM_DELAY_MS` | company_enrichment (optional) | same |
| `MONDAY_JWT_AUDIENCE_MODE` | optional; `enforce` (default) or `report` (draft measurement only) | same |
| `PORT` | server | set by monday-code |

---

## 4. Routing

| Method + path | Feature | Auth |
| --- | --- | --- |
| `POST /` | Company Enrichment (compatibility — existing block URL) | monday JWT |
| `POST /company-enrichment` (and `/company-enrichment/`) | Company Enrichment | monday JWT |
| `POST /customer-name-split` (and `/customer-name-split/`) | Customer Name Split | monday JWT |
| `POST /monday/split-name` | Customer Name Split (compatibility) | monday JWT |
| `GET` / `HEAD` `/` and `/health` | health check (`OK`) | none |
| anything else | 404 | — |

---

## 5. Implementation steps

Incremental; the full test suite must pass after every step.

1. **Core:** create `app/core/{config,security,logging,blocks}.py` from the existing code. `security.py`
   gains the `exp` requirement and per-route audience check (§3.4); `config.py` the per-feature required
   settings (§3.5).
2. **Lazy enrichment settings:** `env` read on access, `TTL_MS` → function; settings loading moves to the
   app lifespan in `app/core/config.py`.
3. **Company Enrichment feature:** `git mv` into `app/features/company_enrichment/`, update imports, add
   `router.py` / `service.py` / `schemas.py` replacing Flask `index.py` — same 200 ack body, same 400 body,
   same log lines, same background-thread start.
4. **Customer Name Split feature:** `git mv` into `app/features/customer_name_split/`; its `FastAPI()` app
   becomes an `APIRouter`; `boards/` → `processors/`.
5. **Application:** new `main.py` (`create_app`) and `app/api/router.py`; remove `sys.path`, `a2wsgi`,
   Flask, waitress; one root `requirements.txt`.
6. **Tests:** move existing tests, update imports, add the new tests (§7). Target: ≥ 139 existing + new, all passing.

### Behaviour changes (deliberate, each one listed)

| Change | Reason | Safeguard |
| --- | --- | --- |
| Company Enrichment routes require the monday JWT | `Claude.MD` §7: both feature routes protected; today anyone with the URL can start paid research | test on the draft version first; rollback in §9 |
| Both features validate `exp` and `aud` (today: signature only, and only on the split) | monday's docs (§2.2); review finding "High" | staged measure → enforce rollout (§3.4) |
| Missing required settings → monday error (severity 4000) instead of 500 | avoid 30-minute retry storms; clear failure in run history | startup log names every missing key |
| Malformed JSON on the split route → 400 in monday's error format (today: unhandled 500) | `Claude.MD` §10 malformed-payload handling | test added |
| Unknown GET paths → 404 (old Flask answered `OK` to any GET) | explicit routes only; monday's health check uses `/health` | `/` and `/health` keep answering `OK` |

Everything else is behaviour-identical, proven by the moved test suites.

---

## 6. monday.com configuration

### 6.1 Target

- **App:** Company_enrichment (renaming it to "Company Management" is optional and cosmetic).
- **Deployment:** the app's one monday-code deployment. Do not paste a Version URL host into blocks — it
  changes with every version (§2.2); connect the block to the deployment and set only the sub-route.
- **Both blocks:** **Automation block** features (not the discontinued sentence-builder integration),
  action type, sync, inputs `boardId` and `itemId`.

| Feature | Deployment → sub-route | Sentence |
| --- | --- | --- |
| Company Enrichment (existing) | empty / `/` (later optionally `/company-enrichment`) | `Company Enrichment for {Item id} in {board id}` |
| Customer Name Split | `/customer-name-split` | `Split Customer Name for {Item id} in {board id}` |

Set the sub-route in the block's **Deployment** section / **Feature Deployment** widget, or by CLI:
`mapps app-features:build -a <appId> -i <versionId> -d <featureId> -t monday_code -u /customer-name-split`.
Make the version under test **active for you** (App Versions → ⋯ → "Set as active for me").

### 6.2 Board automations

| Board | Automation |
| --- | --- |
| S.B Leads' Kunden (customers) [Dev] `5099245948` | When an item is created → **Customer Name Split** |
| Sandbox Kunden (customers) `5094068289` | When an item is created → **Customer Name Split** |
| Warm Lead Mining Board (Copy) `5106281544` | When an item is created → **Customer Name Split** |
| Warm Lead Mining Board (Copy) `5106281544` | When Lifecycle Stage changes → **Company Enrichment** (existing) |

Remove the "Company Enrichment" automation from the Kunden Dev board (it runs paid research on customer
items). After changing a block, re-create the board automations that use it.

### 6.3 Checklist to verify in the Developer Center (`Claude.MD` §6)

The Developer Center is not reachable from this environment; these are confirmed by screenshots or by
reading the Logs page:

1. Which app owns the working enrichment deployment (expected: Company_enrichment).
2. Customer Name Split exists as a separate **Automation block** feature in that same app.
3. Both features are connected to the same server-side (monday code) deployment.
4. The **sub-route** of each feature's deployment (expected: empty / `/customer-name-split`) — screenshot
   of each block's Deployment section.
5. Block type: Automation block, not the discontinued "Integration for sentence builder".
6. Which version is live and which is **active** for the tester; the edits were made on that version.
7. `MONDAY_SIGNING_SECRET` and the other settings are on this app (US region) and seen by the deployment
   (startup log `Config OK`, no `Missing environment variables`).
8. Live proof: Logs show `POST /customer-name-split -> customer_name_split` (also visible in
   Monitoring → "Hits by path").
9. JWT claims captured from one legitimate request per block (`aud`, `exp`, `iat`, `accountId` — never
   the token), on the draft and again on live, to fix the audience rule (§3.4).

---

## 7. Tests and acceptance

### 7.1 Test plan

| Area | Tests |
| --- | --- |
| Existing behaviour | all 139 current tests, moved (83 enrichment, 35 split, 21 server/logging) |
| Routing | `/`, `/company-enrichment`, `/customer-name-split`, `/monday/split-name`, unknown route 404; same board id sent to both routes reaches different features |
| Kunden / Warm Lead | long, short and unchanged names on both board types (existing suites) |
| Authentication | on **every** feature route: missing secret → monday error, missing JWT → 401, bad signature → 401, expired / no `exp` → 401, wrong `aud` → 401, `aud` of the other feature's route → 401, valid → 200; `report` mode logs but does not reject `aud` |
| Malformed payloads | invalid JSON, missing item, wrong types |
| Configuration | value from process env, value from monday-code service (mocked), missing required key per feature, no secret value ever appears in log output |
| Feature isolation | changing or removing one feature's router leaves the other feature's tests passing |
| Logging | one request line per call with feature name, board/item ids, correlation id |
| Independence | importing one feature package does not import the other |

All monday.com and OpenAI calls are mocked. No automated test writes to a real board.

### 7.2 Acceptance (from `Claude.MD` §10)

- FastAPI is the only HTTP framework; Flask and `a2wsgi` are gone from code and requirements.
- All existing Company Enrichment behaviour is preserved (existing suites pass unchanged in substance).
- Both automations run through the same deployment, each block on its own route — confirmed in the live Logs page.
- Full test suite passes.
- monday.com feature configuration verified (§6.3).
- JWT signature, `exp` and `aud` enforced in production (§3.4).
- Rollback documented **and rehearsed** on a draft version (§9).

---

## 8. Execution reliability (separate phase)

**Today:** Company Enrichment answers `200 received` immediately and researches in a background thread.
monday therefore records the run as successful before the result is known, and an in-flight run is lost if
the container restarts.

Retry interaction (§2.2): monday retries any non-200 or >1-minute response for 30 minutes, except 4xx /
severity-code responses. The immediate 200 ack avoids those retries today; the cost is that failures are
only visible in the Logs page, never in monday's run history.

**Proposal (phase 2, after the refactor is live):** mark the Company Enrichment block **async**:
1. Request → verify JWT → ack `{"status": "received", "message": "Action has been triggered.", "actionUuid": …}`.
2. Run the existing enrichment (unchanged) in the background.
3. POST the outcome to `payload.callbackUrl` with a JWT signed by the signing secret including `appId`:
   `{"success": true, "outputFields": {}}`, or `{"success": false, "severityCode": 4000, …}` with the
   existing error text.
4. Tests: callback on success, on failure, and callback JWT contents (mocked callback URL).

No queue or job store unless runs must survive container restarts (callback deadline and retries are not
documented — §2.3). Customer Name Split finishes in well under a second and stays synchronous.

**Duplicate-work prevention (same phase).** Duplicates happen today: monday retries, and several
automations can fire for one item (item `3315753724` was enriched 4×). Git versioning does not help with
this, nor with runs lost on restart. Options, smallest first:
1. In-process guard: skip a run when the same `(board_id, item_id)` is already running, and treat a repeated
   `runtimeMetadata.actionUuid` as the same run.
2. Durable execution (only if runs must survive restarts or multiple instances): a persistent job record
   keyed by `actionUuid`. Decided in that phase, not in the refactor.

---

## 9. Deployment, verification, rollback

### Release checkpoints (Git tags)

Git is the code history; a monday app version is only where a tagged commit is deployed.

| Tag | Commit | Meaning |
| --- | --- | --- |
| `release/unified-flask` | `8698ad8` | known-good: both apps in one deployment (Flask + FastAPI), enrichment verified live |
| `release/fastapi-refactor` | refactor commit | created only after the draft passes every check below |

Every deploy records in the release notes: tag, commit, monday app version id, date, test result.

### Deploy

1. Tag the known-good state: `git tag release/unified-flask 8698ad8` (and push the tag).
2. Implement on a new branch from `merge-customer-company-app`; full test suite green.
3. Move `.venv/`, `code.tar.gz` and the spreadsheet out of the folder; push to a **draft** version:
   `npx @mondaycom/apps-cli code:push -i <draft version id> -d .`, with `MONDAY_JWT_AUDIENCE_MODE=report`
   for the measurement step only (§3.4).

### Verify (in order)

0. Set the draft as **active for you**; configure both blocks' sub-routes on it (§6.1); re-create the
   test automations.
1. Startup log: `Config OK`, no `Missing environment variables`.
2. **Company Enrichment first:** change a Lifecycle Stage on Warm Lead (Copy) → Logs show
   `POST / -> company_enrichment 200` and `Item …: updated N columns`.
3. **Then Customer Name Split:** create an item with a name over 100 characters on Kunden Dev and on
   Warm Lead (Copy) → Logs show `POST /customer-name-split -> customer_name_split 200` and the split line.
4. Record the measured `aud` values, fix the audience rule (§3.4), redeploy the draft in **enforce**
   mode and repeat steps 2–3.
5. **Rehearse the rollback** on the draft (below), then redeploy the refactor and repeat steps 2–3.
6. Tag `release/fastapi-refactor`; promote the draft to live; repeat steps 2–3 on live.

### Rollback (recovery steps)

1. `git checkout release/unified-flask` (or the last good `release/*` tag) in a clean checkout.
2. `npx @mondaycom/apps-cli code:push -i <version id> -d .` to the affected version.
3. Restore the block sub-routes recorded for that release, if they were changed.
4. Verify: startup log, then one enrichment and one split run (steps 1–3 above).
5. Record the rollback (tag, version id, reason) in the release notes.

Notes:
- `release/unified-flask` does not check the JWT on enrichment, so rolling back to it also removes that
  protection — acceptable as a short-term recovery only.
- Old Customer Name Split app: keep its automations until the new block is confirmed working, so names
  are never left unsplit; then switch them off so names are not split twice.

---

## 10. Adding a future automation

1. Create `app/features/<name>/` with `router.py`, `service.py`, `schemas.py` and `tests/`.
2. Implement the logic in `service.py`, using `app/core` for settings, authentication and logging.
3. Give the router its own path (`/<name>`) and protect it with `verify_monday_request` (its expected
   audience is derived from that path — §3.4).
4. Add one line to `FEATURE_ROUTERS` in `app/api/router.py` (explicit registration).
5. Add unit tests, a routing test and the auth tests; the existing features' suites must still pass
   unchanged, proving the new feature broke nothing.
6. Create a monday action block in the same app, connected to the same deployment, subroute `/<name>`.
7. Add only the environment variables the feature needs.
8. Deploy to a draft, check its request line in Logs, promote.

The new feature imports nothing from other features. If one ever needs its own scaling or workers, its
folder can be lifted into a separate deployment without touching the others.

---

## 11. Risks and open items

| Risk | Mitigation |
| --- | --- |
| Platform behaviour in §2.3 not stated in the docs | each item has a live check in §6.3 / §9; adjust §6 if a limitation shows up |
| JWT check rejects real monday calls (e.g. unexpected `aud` format) | measure claims on the draft in `report` mode, then enforce (§3.4); rollback in §9 |
| `aud` does not identify the endpoint on live (community report) | record as a verified platform limitation and propose the smallest safe alternative before promoting — never silently disable the check |
| Duplicate enrichment runs (retries, several automations) | duplicate-work prevention in the reliability phase (§8) |
| Customer Name Split block still calls `/` after the refactor | Developer Center configuration (§2.5): sub-route, active version, re-created automations; verify with §6.3 |
| Retries for 30 minutes on 5xx (e.g. split's "Server misconfigured") | settings checked at startup; handlers idempotent |
| Warm Lead (Copy): both features write **Company / Customer Name** | split shortens it at creation; enrichment may later write the researched legal name — confirm the intended final value |
| Two `DEFAULT_BOARD_ID`s (split: hard-coded `5100825258`; enrichment: env var) | kept separate to preserve behaviour; unify only if desired |
| Settings source on monday-code (process env vs. service) | the startup log records which source each key came from (names only, never values) |
