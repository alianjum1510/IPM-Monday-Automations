# Plan — add Address Validator (HERE) to the unified FastAPI app

- Branch: `fastapi-refactor`, HEAD `4a0d0e5`, Comment Builder implemented locally but not committed
  (its plan moved to [PLAN-comment-builder.md](PLAN-comment-builder.md); its §11 deploy is still open).
- Source app: `../MondayAddressValidator-main` (git `438d9f5 Convert HERE address validator`), same
  content as `MondayAddressValidator-main.zip` in this folder. Its own suite: **21 tests, all pass**
  (`python3 -I -m unittest discover -s test`, Python 3.9).
- Status: **implemented locally (2026-11-03), not committed, not deployed.** Full suite 568 passed
  (61 in `app/features/address_validator/`), Python 3.12. §10–11 (Developer Center, deploy) still to do,
  only after an explicit go. Changes from the plan as written, to keep all of the old app's behaviour:
  the auto route is kept as `POST /address-validator`; `MONDAY_API_TOKEN` is optional with the verified
  JWT's `shortLivedToken` as fallback (as the old app did); the payload parsing (`payload.py`) is kept for
  every payload shape, minus the unverified token search.

---

## 1. What the Address Validator is

Today two **Automation Blocks** of a separate monday app, **Address Validator (app 11380387)**, on their
own monday-code deployment (v2 live, v3 draft). Fills a row's address columns from the **HERE Geocoding
API** on the two Address Master boards.

| File | What it does | Lines |
| --- | --- | --- |
| `main.py` | stdlib `http.server`; modes, loop guard, diff-only updates, status | ~490 |
| `here_api.py` | HERE call, Full Address parser, postcode match, result → columns mapping | ~140 |
| `config.py` | column IDs per board, status labels, required fields | ~70 |
| `monday.py` | GraphQL read item / `change_multiple_column_values`, location-column value | ~120 |
| `payload.py` | token and id extraction for every payload shape (blocks, recipes, webhooks) | ~190 |

No third-party packages. Not deployed: `here.py` (comparison script), `code.tar.gz` (old JS version),
`prev_version_Google_API.zip` (old Google + OpenAI version).

| Block (old app) | URL | Mode | Board automation |
| --- | --- | --- | --- |
| "Fill address" | `…/action/address` | `address` — geocode Vollständige Adresse, fill Adresszeile 1, Postcode, Ort, Landkreis, Bundesland, Land, lat/lng, location, status. Never writes Full Address. | When **Vollständige Adresse** changes |
| "Address validator" | `…/action/fields` | `fields` — geocode `Adresszeile 1, Postcode`, check HERE agrees on postcode, refresh Ort … lat/lng, location, **Full Address**. Never writes Adresszeile 1 / Postcode. | When **Adresszeile 1** changes, When **Postcode** changes |
| (old) | `…/action` | auto — picks a mode from what is filled | — |

Boards: `5063711037` (Address Master, original) and `5090777446` (replica). Status column → Done/Complete
or Stuck.

## 2. How many features / blocks — answer: **one feature module, two automation blocks**

**One feature module** (`app/features/address_validator/`): both blocks share the HERE client, the
board map, the loop guard and the update logic. Splitting them into two modules would duplicate all of
that or make one depend on the other.

**Two automation blocks**, one per mode. One block is not enough:

- monday's action block sends only `boardId` + `itemId`, not which column changed (the old README
  states it; the code's column-id branch exists only for webhooks).
- The "auto" mode cannot tell the cases apart. When Full Address **and** Adresszeile 1 + Postcode are
  filled (every row after its first run), auto always picks `fields`. A user who re-enters the Full
  Address would then get `fields` mode, which ignores the new Full Address and overwrites it from the
  old Adresszeile 1 + Postcode. That is wrong.
- So the **route** must carry the mode. This matches the platform rule "the configured endpoint
  decides" (CLAUDE.md §4).

A single block would only work if the "When column changes" trigger passed the changed column into a
block input field. That is not verified, and it would also put the mode into a client-supplied value.
Not proposed.

The auto route `/action` is **not** carried over. The new blocks are created fresh (§3) and none of
them calls it.

| Feature | monday feature type | Route |
| --- | --- | --- |
| Company Enrichment | Automation block | `/company-enrichment` (and `/`) |
| Customer Name Split | Automation block | `/customer-name-split` (and `/monday/split-name`) |
| Vendor Name Split | Automation block | `/vendor-name-split` |
| Comment Builder | Item View | `/comment-builder` |
| **Address Validator — Fill address** | **Automation block** | **`/address-validator/fill`** (mode `address`) |
| **Address Validator — Validate address** | **Automation block** | **`/address-validator/validate`** (mode `fields`) |

## 3. Decision to confirm — move the blocks into Company Management (11727119)

**Recommended:** like Comment Builder, the two blocks become features of the **Company Management** app
on the shared deployment. The old app 11380387 stays live until both boards have switched, then is
uninstalled.

Why not keep the blocks in app 11380387 and just point their URLs at the unified deployment:
- monday signs each block's JWT with **its own app's** Signing Secret. The unified app checks one
  `MONDAY_SIGNING_SECRET` (11727119's). Accepting a second app's secret would mean a per-route secret
  map in `app/core/security.py` — more code and a second secret to manage, for an app you then still
  have to maintain.
- The old blocks have "Connect to monday code" **unticked** (URL typed by hand), and the old server
  **never verifies the JWT** — anyone who knows the URL can make it write to the boards. The move fixes
  that.

Cost of the move: on each of the 2 boards the 3 automations are re-created with the new blocks
(6 in total), and the old ones are turned off at the same moment (§11).

## 4. Target layout

```text
app/features/address_validator/
  README.md        what it is, the two blocks, board automations, settings
  router.py        POST /address-validator/fill and /validate (+ trailing slash), FEATURE
  service.py       action(): modes, resolve_mode, build_updates, finish/mark_stuck, loop guard   (from main.py)
  here.py          HERE geocode, parse_full_address, postcodes_match, map_here_item              (from here_api.py, unchanged)
  boards.py        BOARDS, required fields, get_board_config                                     (from config.py)
  monday.py        get_item_data, update_item, get_column_value, make_location_value             (from monday.py)
  schemas.py       BlockOutput / MondayError for the OpenAPI docs, like vendor_name_split
  tests/
    conftest.py
    test_here.py      parsing, postcode match, mapping, coord rounding           (from ParsingTests)
    test_modes.py     both modes, Stuck cases, loop guard, restart               (from TriggerFlowTests / ActionBlockTests)
    test_router.py    routes → modes, auth, malformed body, errors
```

`payload.py` is **not** carried over: blocks send `payload.inputFields` (or `inboundFieldValues`), which
the shared `app/core/blocks.field()` already reads, and the token comes from `MONDAY_API_TOKEN` (§6).

Changed outside the feature: `app/api/router.py` (one line in `FEATURES`), `app/tests/test_independence.py`
and `app/tests/test_routing.py` (new feature in their lists), `README.md` (routes, settings),
`main.py` docstring. **No new dependency.**

## 5. The port — what changes and what does not

Kept **unchanged** (moved, not rewritten): the HERE query (`limit=1`, `lang=de`, `in=countryCode:`),
Full Address parser incl. Dutch postcode split, `postcodes_match`, `STATE_EN`, `COUNTRY_CODES`, 4-decimal
rounding, the field lists of both modes, required fields for Done, diff-only updates, the location-column
value format, status labels, all column IDs, every log message's wording, HERE/monday 10 s timeouts.

Changed, on purpose:

| | Old | New | Why |
| --- | --- | --- | --- |
| HTTP | `http.server`, any POST path | FastAPI router, two paths | platform |
| Mode | parsed from the URL suffix | each route passes its mode to `service.action(mode=…)` | route decides, no string matching |
| Auth | **none** (JWT only decoded to find a token) | `verify_monday_request`: signature, `exp`, `aud` = route | CLAUDE.md §7 |
| monday token | `MONDAY_API_TOKEN`, else the request's `shortLivedToken` | `MONDAY_API_TOKEN` only (required setting) | same as every other feature; the fallback was the unverified token |
| Settings | `os.environ` read at import time, `.env` file | `app/core/config.setting()` read when a request runs (env, then monday-code) | monday-code secrets are not in `os.environ` at import |
| Success reply | 200 `{"success": true, …}` | 200 `{"outputFields": {}}` (blocks have no output fields) | monday block contract |
| Failure reply | **500** `{"success": false, "error"}` | 400 `severityCode 4000` with the error, via `monday_error` | shows in the automation's activity log. **Note:** monday retries a 500 for up to 30 min; it does not retry 4000. Same as the other features. |
| Webhook `challenge`, column-id from payload, auto mode | supported | dropped | no webhooks or auto block in the new setup |

Sync vs async: the HERE and monday calls stay on `urllib` (sync, as now) — no rewrite to `httpx`. The
route is `async`, reads the body, then runs `service.action` with `run_in_threadpool`, so a slow HERE call
does not block other features. The shared `app/core/monday_client.py` is **not** reused: it reads only
`text` (the validator falls back to `value`) and writes only text columns (the validator writes location
and status JSON). Same reason Company Enrichment keeps its own client.

Loop guard: stays an in-memory dict + lock inside `service.py` (2-minute TTL). It is per process; the
diff-only write is the backstop after a restart or on a second instance — as today. Kept on purpose:
without it, every write fires the other block again.

## 6. Settings

| Key | Required | Notes |
| --- | --- | --- |
| `HERE_API_KEY` | yes | copy from app 11380387 → Server-side code. New on Company Management |
| `MONDAY_API_TOKEN` | yes | already on the unified app. **Verify** its user can read/write boards 5063711037 and 5090777446 (the old app may use a different token) |
| `ADDRESS_COLUMN_LOCATION_ID` | for board 5063711037 | **renamed** from `COLUMN_LOCATION_ID`; copy the value from app 11380387. Without it board 5063711037 gets no location pin (as today) |
| `ADDRESS_COLUMN_*_ID`, `ADDRESS_DONE_STATUS_LABEL`, `ADDRESS_STUCK_STATUS_LABEL` | no | renamed overrides for board 5063711037; defaults are the IDs in `config.py` |
| `ADDRESS_DEFAULT_BOARD_ID` | no | renamed; default `5063711037` |

**Why the `ADDRESS_` prefix:** `DEFAULT_BOARD_ID` clashes. Company Enrichment and Customer Name Split
already use that name (CLAUDE.md §7), so one value on the shared app would silently change the other
feature. `COLUMN_*_ID` and `DONE_STATUS_LABEL` are generic enough to clash with the next feature. They
must be re-entered on Company Management anyway, so renaming costs nothing extra.
`MONDAY_SIGNING_SECRET` and `MONDAY_JWT_AUDIENCE_BASE_URLS` are already handled by the shared check.

Unknown board → the default board's column map is used (unchanged). With JWT and only two boards using
the blocks this is acceptable; a stricter "unknown board → error" is possible but would be a behaviour
change — not proposed.

## 7. Logging

- Request line names the feature: `POST /address-validator/fill -> address_validator 200 (850 ms)`.
- Old `print` lines become `log.info` / `log.error` under logger `address_validator`, same text, with
  `board_id`, `item_id`, `mode` in the payload.
- The HERE query (an address) is logged, as today. **Never logged:** `HERE_API_KEY` (it is in the HERE
  URL — the URL itself is never logged; a HERE HTTP error logs status + first 200 chars of HERE's body,
  as today), the JWT, the monday token.

## 8. Tests (HERE and monday mocked; nothing hits HERE or a real board)

Port all 21 existing tests (same cases, pytest style), plus:

- `/address-validator/fill` runs mode `address`; `/address-validator/validate` runs mode `fields`; with
  and without trailing slash; the same board and item on both routes do different things (routing does
  not depend on board id).
- Auth: missing / invalid / wrong-audience JWT → 401; a token issued for `/fill` is refused on `/validate`;
  missing `MONDAY_SIGNING_SECRET` → refused.
- Missing `HERE_API_KEY` or `MONDAY_API_TOKEN` → `severityCode 4000` "missing setting(s)", HERE never called.
- Malformed JSON, missing `itemId` → 400 monday error; HERE HTTP error and monday API error → 400
  monday error, no write.
- Settings: `DEFAULT_BOARD_ID` does **not** change the validator; `ADDRESS_DEFAULT_BOARD_ID` does;
  `ADDRESS_COLUMN_LOCATION_ID` adds the location column on 5063711037.
- Independence: `address_validator` imports no other feature and no other feature imports it; existing
  suites unchanged.

**Baseline blocker (unchanged from the last plan):** the unified suite needs Python 3.12; this Mac has
only 3.9 (`.venv` too). `brew install python@3.12`, rebuild `.venv`, record the baseline before the
first change.

## 9. Implementation steps (after the go)

1. Python 3.12 venv, run the full suite, record the baseline.
2. Create `app/features/address_validator/`, move `here_api.py` → `here.py` and `monday.py` as they are;
   `config.py` → `boards.py` reading settings through `setting()` lazily.
3. `service.py` from `main.py`'s logic (modes, guard, updates), with `print` → logger and the token from
   settings. No change to the rules.
4. `router.py` + `schemas.py`, register `FEATURE` in `app/api/router.py`.
5. Port and add tests; full suite green.
6. README (feature + top-level), `main.py` docstring.

## 10. monday configuration (Company Management 11727119, draft version)

Two new **Automation Block** features, both with the same settings as the old ones, except the URL:

| Setting | Fill address | Validate address |
| --- | --- | --- |
| Block type | Action, not async | Action, not async |
| Deployment | the app's **monday code** (ticked) | the app's **monday code** (ticked) |
| Route | `/address-validator/fill` | `/address-validator/validate` |
| Input fields | Board Id (`boardId`), Item Id (`itemId`, main) | same |
| Output fields | none | none |
| Sentence | `Fill address from full address for {Item Id} on {Board Id}` | `Validate address for {Item Id} on {Board Id}` |

OAuth scopes: `boards:read`, `boards:write` — check Company Management already has them.

## 11. Deployment and verification — only after an explicit go

1. Before any `mapps code:push`: move **`MondayAddressValidator-main.zip`** out of this folder
   (also `code.tar.gz`, `comment-builder-server-app 2.zip`, `.venv/`). See §13.1.
2. Draft version of Company Management: add `HERE_API_KEY`, `ADDRESS_COLUMN_LOCATION_ID`; create the two
   blocks (§10); push.
3. **Replica board 5090777446 first:** turn off its 3 old automations, create the 3 new ones
   (Vollständige Adresse → Fill address; Adresszeile 1 → Validate; Postcode → Validate).
4. Test on a test row: enter a Full Address → all fields + Complete; edit Postcode to a wrong one →
   Stuck, only status written; edit Adresszeile 1 → Full Address refreshed; check that no loop occurs.
5. Logs page: `POST /address-validator/fill -> address_validator 200`, then the echo `validate` call
   ending in "ignoring — no address input changed"; the other features still answer.
6. Promote; repeat 3–4 on board 5063711037. Then uninstall app 11380387 (keep its code until then).

Never run old and new automations on the same board at the same time: each would fire the other's
blocks and call HERE twice per edit (diff-only writes stop it, but it wastes HERE quota).

## 12. Rollback

- Per board: turn the new automations off and the old ones back on. App 11380387 and its deployment
  are not touched until both boards have run on the new blocks.
- Unified app: revert the commit, push the previous version; no other feature imports `address_validator`.

## 13. Risks and open questions

1. **A GitHub token is in the zip.** `MondayAddressValidator-main.zip` (in this folder) contains
   `.git/config` with a `ghp_…` personal access token in the remote URL; so does
   `../MondayAddressValidator-main/.git/config`. `.gitignore` keeps `*.zip` out of git, but
   `mapps code:push` uploads the folder (there is no `.mappsignore` here). **Move the zip out, and
   rotate the token** (GitHub → Settings → Developer settings) if the zip was ever shared; change the
   remote to use a credential helper instead. The token is not copied into this repo.
2. To verify in the Developer Center: the old app's `COLUMN_LOCATION_ID` value and any other `COLUMN_*`
   overrides it sets; whether its `MONDAY_API_TOKEN` is the same user as Company Management's.
3. HERE quota and billing stay on the same key; nothing changes there.
4. The loop guard is per process (as today); if monday code runs more than one instance, the diff-only
   write ends the chain after one extra HERE call.
5. Failures move from 500 (monday retries) to 4000 (no retry). A HERE outage now shows as a failed run
   in the activity log instead of being retried silently — re-run the automation after the outage.
6. Comment Builder (implemented, not committed) should be committed or set aside first, so the two
   features land as separate commits.
