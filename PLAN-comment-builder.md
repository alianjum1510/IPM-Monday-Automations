# Plan — add Comment Builder to the unified FastAPI app

- Branch: `fastapi-refactor`, HEAD `4a0d0e5 vender name split added`, working tree clean
- Source app: `../comment-builder-server-app` (git `ccf81cb updates`, the Python version; the Node
  version in `../Comments App acc to Sana/comment-builder-server-app` is older and is **not** used)
- Status: **implemented locally (2026-11-02), not committed, not deployed.** Suite: 327 passed before,
  417 passed after (90 new). §11 (Developer Center, deploy) is still to do, after an explicit go.
  Differences from the plan as written: a wrong method on an AI route answers FastAPI's 405
  (`{"detail": …}`), not `{"error": "Use POST."}`; a missing setting answers
  `comment_builder: missing setting(s) …`; the missing-token message no longer names Comment Builder
  (it lives in the shared check).

---

## 1. What Comment Builder is

Today an **Item View** feature of a separate monday app, **Comment Builder (app 11942098)**, on its own
monday-code deployment:

| Part | What it does |
| --- | --- |
| `public/` (≈195 KB, prebuilt) | The page monday shows in the item view: log a comment on a deal, history, mentions, emoji |
| `POST /api/ai/write` `{prompt}` → `{text}` | "Write with AI" — drafts an update (OpenAI chat, `gpt-4o-mini`) |
| `POST /api/ai/summarize` `{text}` → `{text}` | "Summarize" — 2–4 bullets from an update |
| `POST /api/ai/autofill` `{comment, options, …}` → `{fields}` | "Autofill" — classifies the comment with the team's category rules (`AUTOFILL_GUIDE`), keeps only allowed values |
| `GET /health` | JSON: `ok`, `signatureCheck`, where each secret was found |

`server.py` is one 676-line stdlib file (`http.server` + `urllib`). Every `/api` call carries monday's
**session token** (from `monday.get('sessionToken')` in the page), checked for HS256 signature with the
app's **Client Secret**, `exp`, and `dat.app_id`. Per-user and per-IP limit: 30 AI calls a minute. Body
limit 64 KB.

**One feature:** Comment Builder becomes one feature module (`comment_builder`) — one Item View, one
page, three API routes. No automation block.

## 2. How it differs from the three automation blocks

| | Company Enrichment, Customer / Vendor Name Split | Comment Builder |
| --- | --- | --- |
| monday feature type | Automation block (server-to-server POST) | Item View (a page in an iframe + browser `fetch`) |
| Token | Integration JWT, signed with the **Signing Secret**, `aud` = route | Session token, signed with the **Client Secret**, `dat.app_id` |
| Unauthenticated routes | none | the page and its assets (the iframe loads them with no header) |
| Error shape the caller expects | monday's `severityCode` 4000 format | `{"error": "<message>"}` — the page shows `error` |

So Comment Builder gets its own router and a second token check in `app/core/security.py` (§6), and is
registered through the same `Feature` / `FEATURES` list like the others.

**Path conflict:** the unified app's `GET /` and `/health` are the health check monday's health checker
uses. The page cannot stay at `/`; it moves to **`/comment-builder`**.

## 3. Decision — an Item View feature in the same app (decided 2026-11-02)

Comment Builder becomes a **fourth feature of the Company Management app (11727119)**, on the same
deployment as the other three. In the Developer Center: Company Management → Features → **Create
feature → Item View** "Comment Builder", Deployment = the app's **monday code**, route `/comment-builder`.

| Feature | monday feature type | Route |
| --- | --- | --- |
| Company Enrichment | Automation block | `/company-enrichment` (and `/`) |
| Customer Name Split | Automation block | `/customer-name-split` |
| Vendor Name Split | Automation block | `/vendor-name-split` |
| **Comment Builder** | **Item View** | **`/comment-builder`** |

What this means:
- The session token is signed with the **Client Secret of 11727119**, and `dat.app_id` is 11727119.
- The view is a new feature, so **each board adds "Comment Builder" again** from the Company Management
  app in the item view. Until then the old view (app 11942098) keeps working on its own deployment;
  once every board has switched, the old app is uninstalled.

**To verify in the Developer Center before deploying** (not verified yet):
1. An Item View on monday code can be given the route `/comment-builder`. If it can only open the root
   `/`, the page cannot go there (it is the health check) — then stop and decide again; the fallback is
   an external-URL deployment pointing at `<Live URL>/comment-builder`.
2. The Company Management app's Client Secret (Basic Information) and Live URL.
3. The app's OAuth scopes cover what the page does in monday (read items and updates, create and edit
   updates, read users): copy them from Comment Builder's **Permissions** page.

## 4. Target layout

```text
app/features/comment_builder/
  README.md        what it is, routes, settings, how to rebuild the page
  router.py        page + assets (no auth), /api/ai/* (session token), /comment-builder/health
  service.py       write / summarize / autofill: prompts, AUTOFILL_GUIDE verbatim, OpenAI call, value filter
  ratelimit.py     30 calls/min per user and per IP (moved unchanged)
  schemas.py       request/response models for the three API routes
  static/          the built page, copied unchanged from ../comment-builder-server-app/public/
    index.html
    assets/index-d7f8d9ef.js, index-B7bP6c-l.css, updates-64f148eb.css
  tests/
```

Changed outside the feature: `app/core/security.py` (`verify_session_token`, §6), `app/api/router.py`
(one line in `FEATURES`), `app/tests/test_independence.py` (new feature in its lists),
`app/tests/test_routing.py`, `README.md` (routes, settings), `main.py` docstring. No new dependency:
OpenAI stays on `urllib` (as now); PyJWT is already installed.

## 5. Routes

| Method + path | Auth | Notes |
| --- | --- | --- |
| `GET`/`HEAD` `/comment-builder`, `/comment-builder/` | none | `index.html`, `Cache-Control: no-cache` |
| `GET` `/comment-builder/{sub-path}` with no file extension | none | `index.html` — monday may open the view on a sub-path (kept from `serve_static`) |
| `GET` `/assets/{file}` (also `…/assets/{file}` under `/comment-builder/`) | none | `immutable`, 1 year; 404 JSON for a missing asset, never HTML; path-traversal check kept |
| `POST` `/api/ai/write`, `/api/ai/summarize`, `/api/ai/autofill` | session token | unchanged request/response bodies and messages |
| `GET` `/comment-builder/health` | none | the old `/health` JSON: `ok`, `signatureCheck`, secret **sources** only |
| `GET`/`HEAD` `/`, `/health` | none | unchanged: the shared health check (`OK`) |

`/assets/*` and `/api/ai/*` stay at the root because the built page calls them by absolute path
(`/assets/…` in `index.html`, `` fetch(`/api${path}`) `` in the bundle). Moving them under
`/comment-builder/` means changing `v4/` and rebuilding — a separate step (§11), not part of this move.

Behaviour dropped on purpose: the old server answered **any** unknown path with the page; here only
`/comment-builder…` does, and anything else is a 404 like the rest of the app.

## 6. Authentication

A FastAPI dependency on the three `/api/ai/*` routes, same rules as `read_session_token()`:

1. `Authorization` (with or without `Bearer `) must be a 3-part token → else 401 "Missing monday session token…"
2. HS256 signature with `MONDAY_CLIENT_SECRET` → else 401 "Invalid monday session token. Reload the page."
3. `exp`, when present, not passed → else 401 "monday session expired. Reload the page."
4. `dat.app_id`, when present, equals `MONDAY_APP_ID` (default `11727119`) → else 403 "This session belongs to another app."

Errors in `{"error": …}`, as the page expects.

**One deliberate change:** today, without a client secret, signatures are **not checked** (`signatureCheck:
off`), so anyone can spend the OpenAI key. In the unified app the client secret is **required**: missing →
500 `{"error": "MONDAY_CLIENT_SECRET is not set…"}` and a startup log line, like the other features'
required settings.

Placement: `app/core/security.py`, as `verify_session_token` beside the block check
`verify_monday_request`. Every View feature this app gets later (board view, dashboard widget, item view)
sends the same session token signed with the same Client Secret, so they reuse it.

## 7. Settings

| Key | Required | Notes |
| --- | --- | --- |
| `OPENAI_API_KEY` | yes | already on the unified app (enrichment uses the same name) |
| `MONDAY_CLIENT_SECRET` | yes | Client Secret of **Company Management (11727119)** — not the Signing Secret, not Comment Builder's |
| `MONDAY_APP_ID` | no | default `11727119` |
| `COMMENT_BUILDER_OPENAI_MODEL` | no | default `gpt-4o-mini` |

Why a new model name: **`OPENAI_MODEL` clashes.** Enrichment reads it too (default `gpt-4o`). Shared, a
model chosen for enrichment's web research would silently change Comment Builder (and its cost), or the
other way round.

Settings come from `app/core/config.py` (process env, then monday-code Secrets / Environment variables).
Two small differences from `server.py`, both on purpose: the `.env` file is not read (local runs use the
environment, as the other features do), and only the first value found is used (the old server tried
every source's value for the client secret).

## 8. Behaviour kept unchanged

- Prompts (`write`, `summarize`), `AUTOFILL_GUIDE`, temperatures, `max_tokens`, `response_format`, the
  80-value / 8-example / 4000- and 12000-char limits, the allowed-value filter, `dueDate` and `transcript` checks.
- Error messages and status codes: 400 (empty input, invalid JSON), 401/403 (token), 405, 413 (body > 64 KB),
  429 (rate limit), 502 (OpenAI error, with OpenAI's message), 500.
- Rate limit: 30/min per user id and per IP (`X-Forwarded-For` first hop), in memory, per process.
- OpenAI calls stay synchronous with the 120 s timeout; the routes are plain `def`, so FastAPI runs them
  in its thread pool and one slow call does not block other requests.
- The built page and its assets, byte for byte.

## 9. Logging

- The request line names the feature: `POST /api/ai/autofill -> comment_builder 200 (1840 ms)`.
- The page and asset GETs log at DEBUG (they are many and say nothing), like the health check.
- **Never logged:** the comment, prompt, update text or AI answer (the request log only reads block ids,
  which these bodies do not have), the session token, or a secret. Lines carry `user_id` and `account_id`
  from the verified token.

## 10. Tests (all external calls mocked; nothing sent to OpenAI or monday)

- Page: `/comment-builder`, `/comment-builder/` and a sub-path serve `index.html` with `no-cache`; assets
  serve with `immutable`; a missing asset is a 404 JSON; `../` is refused; `GET /` is still the health check.
- Auth: missing, malformed, wrong-secret, expired, other-app tokens → 401/401/401/401/403 with the old
  messages; missing `MONDAY_CLIENT_SECRET` → refused, never let through; a block JWT (Signing Secret) is
  refused on `/api/ai/*` and a session token on the block routes.
- Each AI route: happy path with OpenAI mocked; empty input → 400; invalid JSON → 400; > 64 KB → 413;
  OpenAI error → 502; `GET` on an API route → 405.
- Autofill: values outside `allowedValues` dropped, case-insensitive match returns the form's spelling,
  bad `dueDate` / non-URL `transcript` dropped.
- Rate limit: the 31st call within a minute → 429.
- Settings: `OPENAI_MODEL` does not change Comment Builder's model; `COMMENT_BUILDER_OPENAI_MODEL` does.
- Independence: `comment_builder` imports no other feature and vice versa; existing suites unchanged.

Baseline: the suite could not be run on this machine — the project needs Python 3.12 and only 3.9 is
installed (`.venv` is 3.9 too). Install 3.12 (`brew install python@3.12`) and record the baseline before
the first change.

## 11. Deployment and verification — only after an explicit go

1. Implement on a branch, full suite green.
2. In a **draft** version of Company Management (11727119): Features → Create feature → **Item View**
   "Comment Builder", Deployment = monday code, route `/comment-builder`. Copy the OAuth scopes from
   Comment Builder (11942098) → Permissions.
3. Add `MONDAY_CLIENT_SECRET` (11727119's Client Secret) as a Secret on the app.
4. `mapps code:push` the unified app to that draft version. Before pushing, move `.venv/`, `*.tar.gz`,
   `code.tar.gz` and **`comment-builder-server-app 2.zip`** out of the folder (§13.5).
5. Open `<draft URL>/comment-builder/health`: `ok`, `signatureCheck: on`, both secrets found.
6. On a test deal, add the view from the draft app: Write with AI, Summarize, Autofill, log a comment.
7. Logs page: each call shows `-> comment_builder 200`; the three automation blocks still answer.
8. Promote the version. Each board adds the new Comment Builder view; when all have, remove the old view
   and uninstall app 11942098.

Later, separately: move `/assets` and `/api/ai` under `/comment-builder/` (change `v4/`, rebuild). Before
**any** rebuild of the page, apply `../comment-builder-server-app/v4-fixes.diff` to `v4/` (photo field,
double mention, Autofill leftovers), or the rebuild undoes those fixes. The build script then writes into
`app/features/comment_builder/static/`.

## 12. Rollback

- Comment Builder: the old app (11942098) and its deployment are not touched until every board has
  switched, so going back is using the old view again.
- Unified app: revert the commit and push the previous version; the three existing features do not
  depend on `comment_builder`.

## 13. Risks and open questions

1. Boards must add the new view by hand; comments already logged stay (they are monday updates on the
   items, not data of the app).
2. Not verified: the Item View route `/comment-builder` on monday code (§3); whether the live Comment
   Builder runs the Python build (`index-d7f8d9ef.js`) — the plan assumes it does.
3. One OpenAI key for all features: one bill, one rate limit at OpenAI. A separate key is possible
   (`COMMENT_BUILDER_OPENAI_API_KEY`) if spending must be tracked apart.
4. The rate limit is per process and resets on restart, as today.
5. **A real OpenAI key is in two zips.** `comment-builder-server-app 2.zip` in this folder and
   `../comment-builder-server-app.zip` both contain its `.env`. `.gitignore` keeps the zip out of git,
   but `mapps code:push` uploads the folder, so the zip must be moved out before any push. The key
   should be rotated if either zip was shared. It is not copied into this repo.
