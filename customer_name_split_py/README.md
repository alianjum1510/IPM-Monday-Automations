# customer_name_split (Python), merged

One monday.com integration app that replaces both **Kunden-board-customer-name-split** and **customer_name_split_py**. The board the automation runs on decides what happens:

| Board | Listed in (app/boards/\_\_init\_\_.py) | Flow | What it does |
|---|---|---|---|
| S.B Leads' Kunden (customers) [Dev] (`5099245948`), Sandbox Kunden (customers) (`5094068289`) | `KUNDEN_BOARD_IDS` | [app/boards/kunden.py](app/boards/kunden.py) | Reads **Kundenname (voll)** (the item name, never changed) and writes **Kundenname (Teil 1)** (≤ 100 chars) and **Kundenname (Teil 2)** (the overflow) |
| Any other board, e.g. Warm Lead Mining Board (Copy) (`5106281544`) | | [app/boards/warm_lead.py](app/boards/warm_lead.py) | If **Company / Customer Name** is over 100 chars, cuts it in place and moves the overflow to **Company / Customer Name 2**, exactly as the old customer_name_split app did on any board |

Both flows behave exactly as the two separate apps did. Board and column ids are now in the code instead of environment variables (see [Board and column ids](#board-and-column-ids)).

Stack: FastAPI, PyJWT, httpx. Tests: pytest.

## How the split works (both boards)

| Step | Rule |
|---|---|
| 1 | Name is normalised (NFC, repeated spaces collapsed, trimmed). Length counted in real characters, so `ü` is 1 |
| 2 | 100 chars or less → no split. Kunden: whole name goes to Teil 1, Teil 2 is cleared. Warm Lead: nothing is written |
| 3 | Over 100 → cut at the **last space** at or before char 100 |
| 4 | No usable space → cut after the last `, ; / - & .` |
| 5 | Still nothing (one 100+ char token) → hard cut at 100 |
| 6 | Boundaries that would leave part 1 under 50 chars are ignored |

Example: `Zweckverband Gemeinschaftliche Wasserversorgung und Abwasserentsorgung Landkreis Oberallgäu Süd Kempten Immenstadt` (114) → part 1 (95) + `Kempten Immenstadt` (18).

No infinite loop on either board. Kunden only writes the parts whose value changes and never touches the full name, so a re-run finds nothing to do. Warm Lead's write of part 1 fires the trigger again, but that value is ≤ 100, so the second run is a no-op.

## Project layout

```
app/
  main.py          FastAPI app, POST / and /monday/split-name, GET /health; picks the board's flow
  boards/
    __init__.py    board id -> flow (KUNDEN_BOARD_IDS -> kunden, anything else -> warm_lead)
    kunden.py      S.B Leads' Kunden [Dev] / Sandbox Kunden: full name -> Teil 1 + Teil 2
    warm_lead.py   Warm Lead Mining Board copy: Customer Name -> Customer Name + Customer Name 2
  split.py         split_customer_name(), pure logic, shared by both boards
  monday.py        GraphQL column lookup by title, read, single mutation write
  block.py         block input parsing and monday's error format
  auth.py          JWT verification dependency (Signing Secret)
  config.py        env settings and secrets
tests/
  test_split.py      split logic cases
  test_routing.py    which board runs which flow, shared input/auth cases
  test_kunden.py     Kunden flow against a mocked monday API
  test_warm_lead.py  Warm Lead flow against a mocked monday API
```

A new Kunden board: add its id to `KUNDEN_BOARD_IDS` in `app/boards/__init__.py` and redeploy. Any other board just needs the automation; it runs the Customer Name flow.

## Setup in the monday Developer Center

This folder is deployed together with `company_enrichment/` as one monday app: the repository root's `main.py` serves it at `/customer-name-split`. The block goes in the **same** monday app as the Company Enrichment block, and all boards' automations point at it.

1. **Host on monday → Server-side code → Environment variables**: `MONDAY_SIGNING_SECRET` (the Signing Secret of **that** app) and `MONDAY_API_TOKEN` (see [Config](#config)). They're set on the app, not a version.
2. Deploy (see below), then copy the **Version URL** from **Server-side code → General**.
3. **Features → Automation Block** (keep the existing one or create it):
   - Block name `Split Customer Name`, Block type **Action**, async **off**, ✅ Connect to monday code
   - Input fields: `boardId` (display name `board id`) and `itemId` (display name `Item id`), both with source **Sentence**
   - Output fields: none
   - Execution URL: the Version URL + `/customer-name-split` (`/customer-name-split/monday/split-name` works too)
   - Workflow builder **Off**, Automation builder **On**
   - Sentence: `Split Customer Name for {Item id} in {board id}`
   - **Save changes**
4. OAuth scopes: none needed (the app uses `MONDAY_API_TOKEN`).
5. On **each** board (Kunden Dev, Kunden Sandbox, Warm Lead copy) → **Automate → Create custom automation** → **When an item is created** → action **Split Customer Name** → map Item and Board from the trigger.

The `MONDAY_API_TOKEN` owner needs access to all of these boards.

## Deploy

From the **repository root**, together with the enrichment app:

```bash
mapps code:push -i <APP_VERSION_ID> -d .
```

The app version id is the number after `app_versions/` in the Developer Center URL.

## Run locally

From the **repository root** (see the root README); this app is then at `http://localhost:8080/customer-name-split`.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q                                   # every test, this app's included
export MONDAY_SIGNING_SECRET=... MONDAY_API_TOKEN=...
uvicorn main:app --reload --port 8080
```

## Config

| Env var | Default | Purpose |
|---|---|---|
| `MONDAY_API_TOKEN` | required | Personal API token sent as `Authorization` on every GraphQL call. `MONDAY_API_KEY` also works |
| `MONDAY_SIGNING_SECRET` | required | General settings → Signing Secret of **this** app. Verifies the JWT monday sends |
| `MAX_NAME_LENGTH` | `100` | Limit for part 1 on both boards |
| `TEIL2_MAX_LENGTH` | unset | Logs a warning if part 2 overflows this |
| `MONDAY_API_VERSION` | `2025-04` | monday GraphQL API version |
| `PORT` | `8080` | HTTP port. monday code sets it itself |

On startup the app logs `Config OK` (or `Missing required config: ...`); check that line after each deploy. Values are cached until the process restarts, so redeploy after changing one.

## Board and column ids

Fixed in the code; change them there and redeploy.

| Where | Name | Value | On monday |
|---|---|---|---|
| `app/boards/__init__.py` | `KUNDEN_BOARD_IDS` | `5099245948` | S.B Leads' Kunden (customers) [Dev] |
| | | `5094068289` | Sandbox Kunden (customers) |
| `app/main.py` | `DEFAULT_BOARD_ID` | `5100825258` | used when the automation doesn't send `boardId` |
| `app/boards/kunden.py` | `SOURCE_COLUMN_ID` | `name` | Kundenname (voll), the item name. Read only |
| `app/boards/kunden.py` | `PART1_COLUMN_ID` | `text_mkt92ar9` | Kundenname (Teil 1) |
| `app/boards/kunden.py` | `PART2_COLUMN_ID` | `text_mksb1npw` | Kundenname (Teil 2) |
| `app/boards/warm_lead.py` | `SOURCE_COLUMN_TITLES` | `Company / Customer Name` | found by title |
| `app/boards/warm_lead.py` | `TARGET_COLUMN_ID` | `text_mm7qvqph` | Company / Customer Name 2 |

The Kunden column ids are shared by Dev and Sandbox, as in the old app.

The old apps' column env vars (`SOURCE_COLUMN_ID`, `PART1_COLUMN_ID`, `TARGET_COLUMN_ID`, `*_COLUMN_TITLES`, `DEFAULT_BOARD_ID`) are no longer read and can be deleted from the Developer Center.

Once the Kunden boards' automations use this app's block and work, turn off the old Kunden app's automations so the name isn't split twice.

## Secrets

* **Inbound** (monday → app): every call carries a JWT signed with the app's Signing Secret. `auth.py` verifies it and rejects anything else with a 401.
* **Outbound** (app → monday): every GraphQL call sends the fixed `MONDAY_API_TOKEN`, so the app acts as the user who owns that token.

Secrets are never committed (`.env` is git-ignored). `config.get_secret()` reads a plain env var first (local runs, tests), then monday-code's Secrets and Environment variables through the `monday-code` SDK.

```bash
mapps code:env -m set -i <APP_ID> -k MONDAY_SIGNING_SECRET -v <signing secret>
mapps code:env -m set -i <APP_ID> -k MONDAY_API_TOKEN -v <api token>
mapps code:env -m list-keys -i <APP_ID>
```

## Behaviour notes

* **Kunden**: Teil 1 and Teil 2 are always derived from the full name, so each run **overwrites** them. Edit the full name, not the parts. If the name is later shortened to ≤ 100, Teil 2 is cleared.
* **Warm Lead**: Customer Name 2 is **overwritten** with the overflow when a split happens, and the previous value is logged. If the name is later shortened to ≤ 100, Name 2 is left alone.
* Errors come back in monday's format, so they show in the automation's activity log.
