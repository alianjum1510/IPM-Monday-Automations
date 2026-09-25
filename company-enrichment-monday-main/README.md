# Company Enrichment — monday workflow block

Deep-research enrichment for German company leads. A workflow action block on
app **11727119**, version **16166035**, running on monday-code.

```
"Company Enrichment for {Item id} in {board id}"
        ↓ POST /
   ack in ~5ms  →  monday's runner is free
        ↓ (detached)
   read item → research the company on the web → write ~26 columns back
```

Runs on both lead-mining boards, which carry **the same column titles behind
different column ids**:

| Board | Name |
| --- | --- |
| 5100825258 | 🟢Warm Lead Mining Board🟢 |
| 5100463291 | 🔵Lead Mining Board🔵 |

That is why [mapping.js](src/lib/mapping.js) resolves columns **by title**. A
column missing from a board is skipped, so one deployment serves both.

## Provenance

The original source was not recoverable — monday-code has no download, and no
copy existed locally or in git. This project was rebuilt from three things: the
app manifest (`mapps manifest:export`), 30 days of console logs, and the master
research prompt. Log message shapes (`Action received`, `Background enrichment
done`) are kept identical so historic log searches still match.

## The changes in this rebuild

**1. The email goes to `Company Email`, not `Email`.**
`Email` (`lead_email`) holds the mined human contact's address; enrichment
returns the company's general address from the Impressum, so writing it to
`lead_email` destroyed mined data. `Email` is now in `NEVER_WRITE` and the value
goes to `Company Email` (`email_mm6a4nxf` / `email_mm6ar88x`).

**2. Empty fields are filled with `N/A`:**

| Column type | Empty value becomes | Why |
| --- | --- | --- |
| text, long text | `N/A` | plain string |
| dropdown | `N/A` label | created via `create_labels_if_missing` |
| link, email, phone | `N/A` | these carry their own display label, so the cell reads N/A instead of sitting blank |
| numbers, date, country | left empty | monday parses these into a numeric/ISO value and has nowhere to keep the string `N/A` |

`change_multiple_column_values` is **all-or-nothing**, so one value monday
dislikes would discard the whole write. [`writeColumns`](src/services/monday.js)
absorbs that: it drops the column monday names in the error, logs it, and
retries the rest. Each run logs `[N/A filled: n, left empty: n]`.

**3. `Lifecycle Stage` moves to `Data authentication required` — unless the lead
has already moved on.**
The old build wrote the data and left the stage alone, so an enriched lead still
read `Inbound` and nothing downstream knew it was ready for a human to
authenticate. The stage is now part of `COLUMN_PLAN` as a fixed value, written
in the **same mutation** as the data — the two can never disagree.

That write used to be unconditional, and a run takes **minutes**. A lead that
booked a discovery call while its enrichment was in flight got pulled back from
`Discovery Booked` to `Data Authentication Required` when the run finished — last
write wins, and enrichment was always last. So the stage is now **re-read
immediately before the write** and only moves when the lead is still on a
pre-enrichment stage:

| Stage on the item at write time | Stage write |
| --- | --- |
| empty, `Inbound` | proceeds |
| any `Data Authentication …` variant | proceeds (a re-run) |
| `Discovery Booked`, `Data Complete`, `Disqualified`, `Nurture List`, `Short Route- Discovery`, anything else | **held** — logged as `lifecycle stage=held at "…"` |

It is an **allowlist** ([`LIFECYCLE_STAGE_SOURCES`](src/lib/mapping.js)), so a
downstream label added to the board later is protected without a code change; a
board whose leads arrive on some other starting stage sets the
`LIFECYCLE_STAGE_SOURCES` env var. The data columns are written either way —
only the stage is held. monday has no compare-and-swap, so the race is narrowed
from minutes to milliseconds, not closed.

**4. No option is ever invented on a status or dropdown column.**
Writing the stage as the literal string `Data authentication required` made
monday create a *second* label beside the board's own `Data Authentication
Required`, differing by one capital letter — `create_labels_if_missing` does
that. Same bug put a `DE` option into `Country Code`, which is a list of
**dialling codes**. So:

- Status and dropdown columns are matched against the labels the column
  **already has** — case- and punctuation-insensitive, lowest index wins, and
  the stage is written by `{index}` so no string can create anything.
- `Country Code` gets the dialling code (`+49`), derived from the researched
  phone numbers and falling back to an ISO→dialling map. The **ISO** code still
  goes to the `Country` column, which wants it. Longest match wins so `+1`
  cannot swallow `+212`.
- A researched value with no matching option is written to **Comments** as
  `<Column> (no matching option): <value>` and named in the run log, rather than
  dropped or invented. `N/A` filling is unchanged.
- A dropdown with no labels of its own is still treated as free text.

**5. Web-search citations are stripped.**
`web_search` returns markdown-link citations, so `Contact Name` arrived as
`Michael Dietzel; Boris Sobot — Vorstand ([svg-sued.de](https://…?utm_source=openai))`.
[parse.js](src/lib/parse.js) unwraps markdown links, drops `utm_source=openai`,
and removes parenthesised bare domains — except in the fields whose *job* is to
cite a source (`HRB_CONFIDENCE`, `COMPANY_STATUS`, `VERIFICATION_SOURCE`,
`NOTES` …), where the citation is the point.

**6. `Industry` and `Job Function` are filled.**
Both were absent from `COLUMN_PLAN` and from the prompt, so the model was never
asked for them and nothing was ever written. They are not text or dropdown
columns — they are **`board_relation`**, and the cell holds a link to an item on
a taxonomy board:

| Column | Taxonomy board | Items |
| --- | --- | --- |
| `Industry` | 5094116229 *Subitems of Sandbox Hauptbranchen & Unterbranchen* | 52 |
| `Job Function` | 5095332326 *Sandbox Abteilung & Funktion* | 197 |

Both lead boards point at the **same** two taxonomy boards. The connected board
is read from `settings_str.boardIds`, **not** `boardId`: the cold board's
`Industry` column (`board_relation_mm5b6cag`) has no `boardId` key at all, so
reading that field alone would have filled the warm board only.

This mattered beyond two blank cells. `Hauptbrachen` and `Industry Score` mirror
through `Industry`, `Department` and `Role Score` mirror through `Job Function`,
and all four feed the `Initial Lead Score` formula — so every enriched lead was
scored on empty inputs. Before this change, every item on both boards read
`Industry Score = null`, `Role Score = null`, `Initial Lead Score = ""`.

The taxonomy is **German**, and the names carry the scoring weight in them
(`Großhandel (Industrie-; Arbeitsschutz-; Hygiene-; …)`), so a free-text answer
would almost never match. The exact list is therefore injected into the prompt
and the model is told to echo one line back character for character. That adds
roughly 6.8k characters to the prompt.

Matching then follows the same principle as change 4 — **nothing is ever created
on a taxonomy board**, because an invented industry is a scoring error that looks
like data. [`matchTaxonomyItem`](src/lib/taxonomy.js) tries, in order:

1. the name exactly as the board spells it, after folding case, `&`/`und`, and
   umlauts (`ä`→`ae`, `ß`→`ss`), so `industrie und produktion` still reaches
   `Industrie & Produktion`;
2. both sides cut to the segment before the first bracket or semicolon, so
   `Großhandel` reaches `Großhandel (Industrie-; …)`;
3. a prefix ending on a **word boundary**, shortest name first. The boundary is
   the point: without it `Auto` reaches `Automobilindustrie (inkl. …)` and four
   characters decide an Industry Score.

Anything unmatched is written to `Comments` as
`Industry (no matching option): <value>` and named in the run log — a wrong link
is worse than no link, because no link is logged and recoverable.

Four names exist **twice** on the Job Function board with different Role Scores
behind them — `Geschäftsführer` is 13 on one row and 10 on the other, and
`Logistikmanager`, `Scrum Master` and `Technikvorstand (CTO)` also collide. Ties
break to the **lowest item id**, the same "oldest wins" rule `findStatusLabel`
uses, so the lead score cannot depend on the order monday returned rows in. Every
collision is reported in the run log as `ambiguous taxonomy: …`.

The two taxonomies are read once per container and cached for
`TAXONOMY_TTL_MS` (default 10 minutes), so a newly added industry becomes
matchable without a redeploy and a run normally spends no extra queries on them.

## What gets written

29 columns, from the prompt's output block plus the `EXTRA FIELDS` section that
supplies the board's structured fields (address parts, phones, company email),
the two `CLASSIFICATION FIELDS` relations, plus the fixed `Lifecycle Stage`:

`Lifecycle Stage`, `Company / Customer Name`, `Full Address`, `Address Line 1–3`, `Postal Code`,
`City`, `State`, `District`, `Country`, `Country Code`, `Registration Number`,
`D&B Number`, `Website`, `LinkedIn Profile`, `Contact Name`, `Company Email`,
`Main Phone`, `Mobile Number`, `Fax`, `Phone Type`, `Company Size`,
`Estimated Annual Revenue`, `Company Structure`, `Ownership Type`, `Industry`,
`Job Function`, `Comments`.

The VAT number, both confidence ratings, registry court, Handelsregister
verification, company status and the full NOTES have no column of their own, so
they are collected into **Comments** — that is the verification trail the prompt
works so hard to produce.

## Research

[prompt.js](src/lib/prompt.js) holds the master prompt **verbatim** — the
confidence rules and the source whitelist are the product, so don't reword them.
It runs through the OpenAI **Responses API with the `web_search` tool**: the
prompt demands 15–20 live searches against handelsregister.de, unternehmens-
register.de and Impressum pages, and without the tool the model answers from
memory and every `HIGH` confidence it reports is fiction. If the configured
model rejects the tool, the app logs that and retries without it.

## Environment

Set on the **app** (11727119), not the version, so a redeploy inherits them:

| Variable | Purpose |
| --- | --- |
| `MONDAY_API_TOKEN` | board reads and the column write |
| `OPENAI_API_KEY` | research |
| `OPENAI_MODEL` | model for the Responses API |
| `OPENAI_TIMEOUT_MS` | request timeout (deployment uses 240000) |
| `PORT` | monday-code injects 8080 |
| `DEFAULT_BOARD_ID` | fallback when the payload carries no board id |
| `BOARD_ITEM_DELAY_MS` | pause before the write, to stay under the API's complexity budget |
| `LIFECYCLE_STAGE_SOURCES` | optional, comma-separated: the stages enrichment may move a lead off (default `Inbound,Data authentication required`) |
| `TAXONOMY_TTL_MS` | optional: how long the Industry / Job Function taxonomies are cached (default 600000) |

```bash
npx @mondaycom/apps-cli code:env -i 11727119 -m list-keys
npx @mondaycom/apps-cli code:env -i 11727119 -m set -k OPENAI_MODEL -v <model>
```

## Failure handling

Rebuilt from the failure modes visible in the old deployment's logs:

- **Inactive items** — the old build threw `Cannot change column value for
  inactive items` when the block fired on a deleted/archived item. Item state is
  now checked first and the run exits cleanly.
- **One bad column** — a malformed phone or URL used to sink the whole write.
  `writeColumns` now drops the column monday names in the error and retries.
- **OpenAI 429** — three retries at 1s / 2s / 4s, same ladder as before.
- **A lead that advances mid-run** — the stage is re-read before the write and
  held if the lead moved on, so a discovery call booked during a run is not
  reverted. See change 3 above.
- **An unreadable taxonomy board** — costs `Industry` and `Job Function` for that
  run, logged as `Could not load taxonomy board …`, and the other 27 columns
  still land. The prompt drops both fields entirely when a list is empty, rather
  than asking for a value with no vocabulary behind it.

## Running and deploying

```bash
npm install
node --test "test/*.test.js"    # parser + mapper against the real board schemas
npm start                       # :8080

npx @mondaycom/apps-cli code:push -i 16166035 -d .
npx @mondaycom/apps-cli code:logs -i 16166035 -t console -s history \
  -f "MM/DD/YYYY HH:mm" -e "MM/DD/YYYY HH:mm" -r "."
```

Log history is capped at **30 days** and each query at a **3-day** window.
