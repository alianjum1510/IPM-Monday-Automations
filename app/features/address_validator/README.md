# address_validator — HERE address enrichment (Automation Blocks)

Fills a row's address columns on the **Address Master** boards from the **HERE Geocoding API**.
Moved from the separate app **Address Validator (11380387)**, `../MondayAddressValidator-main`
(`438d9f5`); the rules are unchanged.

## Blocks and routes

monday's automation block sends only `boardId` + `itemId` — not which column changed — so each
block calls its own route and the **route picks the mode**:

| Block | Route | Mode | Board automation | What it does |
|---|---|---|---|---|
| Fill address | `POST /address-validator/fill` | `address` | When **Vollständige Adresse** changes | Geocodes the Full Address and fills Adresszeile 1, Postcode, Ort, Landkreis, Bundesland, Land, Breitengrad, Längengrad, location pin and status. Never overwrites Full Address. |
| Validate address | `POST /address-validator/validate` | `fields` | When **Adresszeile 1** changes, When **Postcode** changes | Geocodes `Adresszeile 1, Postcode`, checks HERE agrees on the postcode, then refreshes Ort … lat/lng, pin and Full Address. Never overwrites Adresszeile 1 or Postcode. |
| (old `/action`) | `POST /address-validator` | auto | — | `fields` if Adresszeile 1 + Postcode are filled, else `address` if Full Address is filled. Kept so the old URL's behaviour still exists; use the two routes above for new blocks (auto picks `fields` on a filled row, so a re-entered Full Address would be ignored). |

Each route also accepts a trailing `/`. If a payload does include a column ID (webhook-style), that
decides the mode on the auto route instead.

Input fields of both blocks: **Board Id** (`boardId`), **Item Id** (`itemId`, main field). No output fields.

## Status

- **Done / Complete** — HERE matched and Adresszeile 1, Postcode, Ort and Land are all filled.
- **Stuck** — inputs empty, HERE found nothing, HERE's postcode disagrees with the user's, or a
  required field is still empty. On a postcode mismatch only the status changes.

A Stuck row is a successful run (200). A HERE or monday API error, or an item that does not exist,
answers monday's error format (`severityCode` 4000), so it shows in the automation's activity log.

## Loop protection

The app writes to trigger columns (`address` writes Adresszeile 1 + Postcode; `fields` writes Full
Address), which fires the automations again. Two guards stop that:

1. After each write the app remembers the item's Full Address, Adresszeile 1 and Postcode
   (2 minutes, in memory) and ignores an event where none of them has changed since.
2. Writes are diff-only. If the echo reaches a fresh instance, it finds nothing to change, writes
   nothing, and the chain ends.

## Files

| File | From the old app | |
|---|---|---|
| `router.py` | `main.py` (HTTP part) | the three routes, token choice, errors → monday's format |
| `service.py` | `main.py` (logic) | modes, `resolve_mode`, diff-only updates, status, loop guard |
| `here.py` | `here_api.py` | HERE call, Full Address parser, postcode match, mapping — unchanged except the key comes from settings |
| `boards.py` | `config.py` | column IDs per board, labels, required fields — read per request |
| `monday.py` | `monday.py` | GraphQL read / `change_multiple_column_values`, location value — unchanged |
| `payload.py` | `payload.py` | ids and column ids from every payload shape |

HERE and monday are called with `urllib` (synchronous, as before); the router runs the work in a
worker thread so other features are not blocked. No third-party package is added.

## Settings

| Key | Required | |
|---|---|---|
| `HERE_API_KEY` | yes | HERE API key with Geocoding & Search enabled |
| `MONDAY_API_TOKEN` | recommended | shared with the other features. Without it, the `shortLivedToken` of the request's verified JWT is used (app scopes only) |
| `ADDRESS_COLUMN_LOCATION_ID` | for board 5063711037 | location column of the original board (old name `COLUMN_LOCATION_ID`). Without it that board gets no pin |
| `ADDRESS_COLUMN_*_ID` | no | column overrides for board 5063711037 (old `COLUMN_*_ID`): `FULL_ADDRESS`, `ADDRESS_LINE_1`, `POSTCODE`, `CITY`, `DISTRICT`, `STATE`, `COUNTRY`, `LATITUDE`, `LONGITUDE`, `STATUS` |
| `ADDRESS_DONE_STATUS_LABEL`, `ADDRESS_STUCK_STATUS_LABEL` | no | labels for board 5063711037 (default `Done` / `Stuck`) |
| `ADDRESS_DEFAULT_BOARD_ID` | no | column map used for unknown boards, default `5063711037` |

The old names got an `ADDRESS_` prefix because the deployment is shared: `DEFAULT_BOARD_ID` is
already another feature's setting. The IDs of board `5090777446` and of the Dev Sandbox board
`5099246179` (same IDs as the original, its own location column) are fixed in `boards.py`.

**✅Sandbox Address Master Board `5094089644`** (English column names) uses the original's IDs
with its own location column, and has **no status column**: its `color_mm0851fj` is "Get Sales
Area", another automation's button. A run there fills the columns but writes no Done/Stuck; a Stuck
run writes nothing and shows only in the Logs.

**Country flag** (boards `5099246179` and `5094089644`, `country_mm2ghytw`): both modes write
HERE's country as monday's country value, `{"countryCode": "DE", "countryName": "Germany"}`
(`countries.py` maps HERE's alpha-3 code). Diff-only, like Land; an unknown code is not written.

**Adresszeile 2** (boards `5099246179` and `5094089644`, `text_mkw9et45`): both modes write HERE's `district`
(the Ortsteil, e.g. `Wiesdorf`) there, but only while the column is empty — a hand-typed `c/o …`
or `2. Etage` is never overwritten. HERE has no real "line 2"; when it has no Ortsteil, nothing
is written. Boards that don't map `address_line_2` are unaffected.

## What changed from the old app

- The block JWT is **verified** (signature, `exp`, `aud` = route) — the old server never checked it.
- Failures answer `severityCode` 4000 (no monday retry) instead of HTTP 500 (retried for 30 min).
- A token inside the request body is never used; only `MONDAY_API_TOKEN` or the verified JWT's.
- Settings are read through `app/core/config.py` (process env, then monday-code), not `.env`.
- Not carried over: the webhook `challenge` reply, `GET` on any path (the app's `/health` does that),
  `here.py` (comparison script), the old Google/OpenAI version.

## monday configuration (Company Management 11727119)

Two Automation Block features, connected to the app's **monday code** deployment:

| Setting | Fill address | Validate address |
|---|---|---|
| Block type | Action, not async | Action, not async |
| Route | `/address-validator/fill` | `/address-validator/validate` |
| Input fields | Board Id (`boardId`), Item Id (`itemId`, main) | same |
| Sentence | `Fill address from full address for {Item Id} on {Board Id}` | `Validate address for {Item Id} on {Board Id}` |

Board automations, per board: Vollständige Adresse changes → Fill address; Adresszeile 1 changes →
Validate address; Postcode changes → Validate address. Turn the old app's automations off on the
same board at the same time.

## Tests

```bash
.venv/bin/pytest app/features/address_validator
```

HERE and monday are faked behind `urllib.request.urlopen`; nothing reaches HERE or a real board.
The old app's 21 tests are ported case for case (`test_here.py`, `test_modes.py`).
