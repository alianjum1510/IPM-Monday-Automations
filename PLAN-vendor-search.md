# Plan — Vendor Search (AI bot that finds German vendors and creates them on the Vendor Mining Board)

- Branch: `add-comment-address-validator`, HEAD `ddf9add Address validator board add`, working tree clean
- Date: 2026-11-17
- Status: **implemented locally (2026-11-17), not committed, not deployed.** Suite: 613 passed before,
  800 passed after (187 new / extended). Step 12.6 (dry run on real products) is ready
  (`python -m app.features.vendor_search.dry_run "<product>"`) but not run: no API keys on this machine.
  §13 (Developer Center, deploy) only after an explicit go. No commit, push or `mapps code:push` without
  an explicit go.
  Differences from the plan as written: `service.select()` (find + check + rank, no writes) is split out so
  the dry run shares it; a `dry_run.py` was added; `app/tests/test_authentication.py` and a docstring line in
  `main.py` also got the new route.
- **Changed after the first live test (2026-11-17, "Nitrile gloves" on v7):** vendor rows are now **named
  after the product** (company in Legal Company Name), created in **group 2** with Search Source
  **"Research Completed"**; the request ends on "Research Completed" **and moves to group 2**, or on
  "Manual research" and **stays in group 1**. Repeats are matched on Legal Company Name + website. The board
  automation "Research Completed → move to group 2" stays (Sana's); it does the same move as the code.
- **Changed after the second live test ("Euro pallets"):** the request row was left empty in group 2. Now
  the **best vendor is written into the request item itself**, and only the other two are created as new
  items, so every row in group 2 holds a vendor. If writing into the request fails, that vendor is created
  as a new item instead. **The code no longer moves the request**: only the board automation "Research
  Completed → move to group 2" does, so without it a completed request stays in group 1.
- **Same product, written differently:** "europallets" / "eurppallets" / "Europaletten" count as the same
  product as "Euro pallets" (code check for case/spaces/hyphens, then one short AI question without web
  search for typos, plurals and translations). Their vendors are never returned again; vendors of a
  different product may be. The existing label is reused.
- **After switching to gpt-4o-mini** (fewer searches, one invented vendor for "zzqlorp 8812"): the check
  prompt now names where to find LinkedIn (site:linkedin.com/company) and employees (LinkedIn, northdata,
  website); Company Size takes the middle of a published range ("51-200" → 126); all 16 states become
  "Bundesweit"; and **pages.py** opens the AI's product page and rejects a vendor whose page is on another
  site, doesn't exist, or doesn't mention the product. Suite: 850 passed.
  Sections below still describe the first design where they differ.

---

## 1. What is being built

A new automation on the **Vendor Mining Board** (`5107912125`, workspace *Dev Sandbox*):

1. A user creates an item in group **"1. Vendor Search in Progress"** (`topics`). The item name is the
   **product** they need (e.g. "iPhone"). This item is the **request**, not a vendor.
2. A monday automation — **"When an item is created → Vendor Search for {item} in {board}"** — calls the
   app. Same pattern as Company Enrichment; the automation is created by us in monday.
3. The bot searches the web for vendors **based in Germany** that sell exactly that product, picks the
   **best 3**, and **creates 3 new items** in the same group, one per vendor, with the vendor's data.
4. The request item's **Search Source** shows the progress:
   - as soon as the run starts → **"AI Bot"** (the bot is working on it)
   - when done → **"Research Completed"** (≥1 vendor created) or **"Manual research"** (none found, or
     the search failed after retries).

The difference from Company Enrichment: enrichment *fills an existing item*; Vendor Search *finds new
companies and creates items*.

## 2. Decisions (agreed 2026-11-17)

| Topic | Decision |
| --- | --- |
| Feature shape | **One new feature module + one new action block** on the existing app (Company Management, 11727119) and the existing deployment. |
| Other features | **Not changed.** Company Enrichment, Customer Name Split, Vendor Name Split, Address Validator, Comment Builder and `app/core/` stay as they are. The only shared edit is registering the feature (one import + one list entry in `app/api/router.py`) and adding its rows to the app-level tests. |
| Trigger | monday automation **"When an item is created"** on board 5107912125 → our block. The bot itself ignores anything not in group `topics` or with Search Source already set. |
| Input | **The item name only.** The Purchase Requirement board is not read. |
| Search area | **Germany only**, set once: `SEARCH_AREA = "Germany"`. Every vendor must have a verifiable German address. A company located outside Germany is rejected even if it delivers to Germany. |
| Same product? | Case and extra spaces are ignored: **"iPhone" = "iphone" = " iPhone "**. **"iPhone 15" is a different product.** |
| Repeat vendors | Checked only against vendor items **on this board** with the same product (same company name or same website). A repeat is skipped and the next best candidate is used. |
| Deleiver Regions | Regions **inside Germany**: **Bundesweit** + the 16 states in German (Baden-Württemberg, Bayern, Berlin, Brandenburg, Bremen, Hamburg, Hessen, Mecklenburg-Vorpommern, Niedersachsen, Nordrhein-Westfalen, Rheinland-Pfalz, Saarland, Sachsen, Sachsen-Anhalt, Schleswig-Holstein, Thüringen). Only these labels are ever written. |
| Company Size | **Number of employees.** |
| Request status | **"AI Bot"** at start → **"Research Completed"** or **"Manual research"** at the end (decided 2026-11-17). |
| Failed AI call | Retried up to 3 times with growing waits. Only if every retry fails → **"Manual research"**. |
| Empty data | A field the AI cannot find is **left empty**. Never guessed, never "N/A" (see §9 — "N/A" in an email column is what broke enrichment on Lead Mining Dev). |
| Search design | Two steps, cost-controlled — §5. |

## 3. The board (verified through the API, 2026-11-17)

Board `5107912125` "Vendor Mining Board". Groups: `topics` "1. Vendor Search in Progress",
`new_group` "2. Criteria Check & ICP Scoring", `group_mm15apmt` "3. Qualified - Ready for Cold Lead",
`group_mkwk11fz` "4. Vendor Pool (review date)", `group_mm94yanz` "5. Removed (reason required)".

| Column | ID | Type | Written by the bot |
| --- | --- | --- | --- |
| Vendor / Request (item name) | `name` | name | vendor's company name |
| Search Source | `color_mm95j9rp` | status — *AI Bot, Manual research, Research Completed, Existing vendor, Inbound vendor* | vendor items: **AI Bot**; request: **AI Bot** while running → **Research Completed / Manual research** |
| Product Categories/ Services | `dropdown_mm9512qn` | dropdown (no labels yet) | the request's product name |
| Country | `country_mm95yne6` | country | Germany (`DE`) |
| Legal Company Name | `text_mm96vz3j` | text | ✓ |
| Complete Address | `text_mm96j9a1` | text | ✓ |
| VAT ID | `text_mm96mq88` | text | ✓ (`DE` + 9 digits only) |
| Year Founded | `numeric_mm965zaj` | numbers | ✓ |
| Company Size | `numeric_mm96dbjz` | numbers | ✓ employees |
| Company Description | `long_text_mm961fmh` | long text | ✓ |
| Website | `link_mm943vd3` | link | ✓ |
| LinkedIn | `link_mm96cqv8` | link | ✓ |
| Company Email | `email_mm968yx7` | email | ✓ (valid address only) |
| Company Phone Number | `phone_mm96a01r` | phone | ✓ (+49, country DE) |
| Name of Contact Person | `text_mm96433x` | text | ✓ |
| Primary Person Contact Number | `phone_mm96btp9` | phone | ✓ |
| Vendor Type | `color_mm95t6mt` | status — *Manufacturer, Reseller, Distributor* | ✓ (only these three) |
| Deleiver Regions | `dropdown_mm96c0jr` | dropdown (no labels yet) | ✓ (fixed list, §2) |
| Certifications | `dropdown_mm96f573` | dropdown (no labels yet) | ✓ (label created if missing) |

Not touched: Lifecycle Stage, Criteria Passed?, ICP Score, ICP Result (defaults to "To be scored"),
Review Date, Existing Vendor, Removal Reason, Purchase Request, Catalogue / Documents, Mined by,
Job Functions and Departments, Industry (and their mirrors).

## 4. Flow of one run

```
monday: item created on 5107912125
  └─ POST /vendor-search  {itemId, boardId}          (JWT checked by the shared feature_router)
       ├─ ack immediately {"outputFields": {}}        (monday times out long before the search ends)
       └─ background thread:
            1. read the item: name, group, Search Source
               - group != "topics"           → stop (log "ignored: not in Vendor Search group")
               - Search Source has a value   → stop (log "ignored: already handled / created by bot")
               - item already running        → stop (duplicate trigger)
            2. request Search Source → "AI Bot"  (shows the bot is working; also blocks a second run)
               product = item name (trimmed); empty → "Manual research"
            3. read existing vendors on this board for the same product (Product Categories label,
               case-insensitive) → their names + website domains
            4. STEP 1 FIND   — 1 AI call (web search): 8–10 German candidates
            5. drop candidates that repeat an existing vendor, repeat each other, or are not in Germany
            6. STEP 2 CHECK  — deep verification of the top candidates, 3 at a time (§5)
            7. rank the verified vendors (§6), keep the best 3
            8. create one item per vendor in group "topics" (§7)
            9. request Search Source "AI Bot" → "Research Completed" (≥1 created) or "Manual research" (0)
               (also on any unexpected error, so a request is never left on "AI Bot" by a crash the
               code can catch)
           10. one summary log line (§8)
```

Loop safety: every vendor item is created **with Search Source = "AI Bot" already set**, so when the
"item created" automation fires for it, step 1 ignores it.

## 5. The search — two steps, built for cost and accuracy

Calls use the OpenAI Responses API with the `web_search` tool, the same API Company Enrichment uses.

**Step 1 — Find (1 call).** Prompt: the product, `SEARCH_AREA`, and the names/websites of vendors already
on the board for this product (so the model doesn't spend slots on them). The model returns a JSON list
of up to 10 candidates: company name, website, city, postal code, vendor type guess, and **one URL proving
they sell this exact product**. Rules in the prompt: Germany-based only (German headquarters/Impressum),
exact product not just the category, manufacturer or official distributor preferred.

**Code filter after Step 1** (no AI cost): drop repeats of existing vendors (normalised name or website
domain), drop duplicates inside the list, drop any candidate whose postal code / city is not a German
format. Rank what is left by the Step 1 data.

**Step 2 — Check (1 call per candidate, 3 in parallel).** For the top 3 candidates, a deep verification
prompt modelled on Company Enrichment's (Impressum, Handelsregister / Unternehmensregister, northdata,
company website): legal name, full address, VAT ID, year founded, employees, description, LinkedIn,
company email, phone, contact person and number, delivery regions (Bundesländer / Bundesweit),
certifications, vendor type, plus `based_in_germany` and the **source URL** for the address.

**Hard Germany gate in code** (not left to the model) — a vendor is accepted only if:
- country is Germany, and
- the address has a 5-digit German postal code and a city, and
- the address was confirmed from an Impressum or a German company register (source URL present).

A candidate that fails is replaced by the next one from the Step 1 list.

**Cost limits:** at most **6 verification calls** per request (3 + up to 3 replacements). Typical run:
1 find + 3 checks = **4 AI calls**; worst case 7. Model: `VENDOR_SEARCH_MODEL` if set, else
`OPENAI_MODEL` — the same model enrichment uses — so cost per check ≈ one enrichment run. If Step 1
returns too few results, no second discovery call is made; the run ends with what it has.

**Retries:** 429, 5xx and timeouts are retried up to 3 times (waits 2 s, 5 s, 10 s). A call that
still fails: in Step 1 → "Manual research"; in Step 2 → that candidate is skipped.

## 6. Picking the best 3

Among verified vendors, in order:
1. **Exact product match** — proof URL shows this exact product.
2. **Verified company data** — legal name, address and VAT ID confirmed from official sources.
3. **Manufacturer or official distributor** over a small reseller.
4. **Established** — years in business, employees, active website / LinkedIn.
5. **Reachable** — company email and phone found.

Fewer than 3 good vendors → only those are created. The list is never filled with weak or unverified
matches.

## 7. Writing to monday

**Create** each vendor with one `create_item` mutation into group `topics`, `create_labels_if_missing: true`:

| Column | Value sent |
| --- | --- |
| name | company name |
| Search Source | `{"label": "AI Bot"}` |
| Product Categories | `{"labels": ["<product>"]}` — if a label already exists that matches case-insensitively ("iphone" vs "iPhone"), **its exact spelling is reused**, so no near-duplicate labels are created |
| Country | `{"countryCode": "DE", "countryName": "Germany"}` |
| text columns | plain string |
| Company Description | `{"text": "…"}` (max 2000 chars) |
| numbers | digits only; an employee **range** ("50–200") is not guessed into one number — left empty |
| links | `{"url": "https://…", "text": "<domain>"}`; only valid URLs |
| email | `{"email": "…", "text": "…"}`; only a valid address |
| phones | `{"phone": "+49…", "countryShortName": "DE"}`; at least 6 digits |
| Vendor Type | `{"label": "Manufacturer" | "Reseller" | "Distributor"}` or omitted |
| Deleiver Regions | `{"labels": [...]}` — only labels from the fixed list in §2 |
| Certifications | `{"labels": [...]}` |

`create_labels_if_missing` is safe for the two status columns because the code only ever sends their
existing labels.

**If monday rejects one column** (e.g. a value it won't accept): the column it names is dropped and the
create is retried. **If monday doesn't name the column** (exactly what happened with enrichment's email —
`error_data` was empty), the create is retried once with only the core columns (name, Search Source,
Product Categories, Country, Legal Company Name, Complete Address) so the vendor is still created.

**Request item**: two `change_column_value` calls on Search Source — **"AI Bot"** at the start, and
**"Research Completed"** / **"Manual research"** at the end. It is not moved, not deleted and not filled
with vendor data.

## 8. Logging

All lines tagged `feature=vendor_search` with `request_id`, `board_id`, `item_id` (the shared logging).
One summary line per run, e.g.

```
Vendor search done: product="iPhone", candidates=9, repeats_skipped=1, not_germany=2,
checked=4, verified=3, created=[3361…, 3361…, 3361…], ai_calls=5, seconds=212, result="Research Completed"
```

Ignored triggers log why (wrong group / already handled / duplicate trigger).

## 9. Lesson carried over from Company Enrichment

On Lead Mining Board (Dev) enrichment failed with `email is not valid`: an empty company email was
filled with `"N/A"`, monday rejected it without naming the column, and the whole write was lost. Vendor
Search therefore never writes placeholders, validates every email/phone/link before sending, and has
the "no column named" fallback in §7. (The enrichment bug itself is **not** fixed by this plan — it is a
separate change to a different feature.)

## 10. Files

New — `app/features/vendor_search/`:

| File | Purpose |
| --- | --- |
| `__init__.py` | |
| `router.py` | `POST /vendor-search` (+ trailing slash); reads `itemId`/`boardId`, acks, starts the run; exposes `FEATURE` |
| `schemas.py` | block input/ack/error models |
| `settings.py` | `SEARCH_AREA`, board/group/column ids, Search Source labels, region list, limits (10 candidates, 3 vendors, 6 checks), required/optional settings |
| `service.py` | `start()` (background thread, log context carried over) and `run()` — the flow in §4 |
| `research.py` | the two OpenAI calls, retries, JSON parsing |
| `prompts.py` | Step 1 and Step 2 prompts |
| `matching.py` | product / company-name / domain normalisation, repeat detection, Germany gate |
| `mapping.py` | verified vendor → `column_values`, all value validation |
| `monday.py` | read request, read existing vendors (paged), create item with column-drop retry, set status |
| `README.md` | what it does, the block, the automation, settings, how to test |
| `tests/` | see §11 |

Edited (additions only):

| File | Change |
| --- | --- |
| `app/api/router.py` | import `FEATURE as vendor_search`, add to `FEATURES` |
| `app/tests/test_routing.py`, `test_independence.py`, `test_config.py`, `conftest.py` | add the vendor_search route / feature rows next to the existing ones |

No new dependencies — `requests`, `httpx` and the shared core already cover it.

## 11. Tests (all external calls mocked; nothing writes to a real board)

- Route: valid call acks and starts a run; missing ids → monday error; malformed JSON; bad/missing JWT → 401.
- Ignored: item not in `topics`; Search Source already set (incl. "AI Bot"); duplicate trigger.
- Product matching: "iPhone" = "iphone" = " iPhone "; "iPhone 15" ≠ "iPhone".
- Repeats: existing "Tech World" for "iPhone" (by name, by website, with/without GmbH, www.) is skipped and replaced.
- Germany gate: Austrian/Swiss address, missing postal code, no address source → rejected and replaced.
- Ranking and limits: never more than 3 created; fewer than 3 good → only those; max 6 checks.
- Mapping: every column's format; bad email/phone/URL/VAT dropped; employee range left empty; region labels outside the list dropped; existing dropdown label spelling reused.
- monday rejects a named column → dropped and retried; rejection without a column → core-only retry.
- Request status order: "AI Bot" is written before any search; then "Research Completed" (≥1 created),
  "Manual research" (0 found), "Manual research" (AI failure after retries), "Manual research" (unexpected error).
- Independence: the feature imports nothing from other features.
- Full suite still passes (baseline recorded before any change — see §12 step 0).

## 12. Implementation steps (after "implement")

0. Create a Python 3.12 environment with `requirements.txt` + `requirements-dev.txt` and record the
   baseline test result. (The repo's `.venv` is Python 3.9 without the dependencies, so the baseline
   could not be run during planning.)
1. `settings.py`, `matching.py`, `mapping.py` + their tests.
2. `prompts.py`, `research.py` + tests with mocked OpenAI.
3. `monday.py` + tests with mocked GraphQL.
4. `service.py`, `router.py`, `schemas.py` + tests; register in `app/api/router.py`; app-level test rows.
5. Full suite; README.
6. **Local dry run** against the real board in read-only mode (find + check, print what would be
   created, write nothing) on 2–3 products, to check result quality and measure time/AI calls.
7. Stop and report. Deployment only after an explicit go.

## 13. monday setup (after an explicit go)

1. Developer Center → Company Management (11727119) → Features → **Create feature → Automation block
   (action)** "Vendor Search": sentence *"Vendor Search for {Item} in {Board}"*, input fields **itemId**
   and **boardId** (same as Company Enrichment), URL `/vendor-search`, deployment = the app's monday code.
2. Optional setting `VENDOR_SEARCH_MODEL` (otherwise `OPENAI_MODEL`). No other new settings —
   `MONDAY_API_TOKEN`, `OPENAI_API_KEY`, `MONDAY_SIGNING_SECRET` already exist on the app.
   If `MONDAY_JWT_AUDIENCE_BASE_URLS` is enforced, the new route is covered by the same base URL.
3. Deploy a **draft version**, then on board 5107912125 create the automation
   **"When an item is created → Vendor Search for {item} in {board}"**.
4. Test: create "iPhone" in group 1 → request shows "AI Bot" within seconds → 3 vendor items with
   Search Source "AI Bot" → request changes to "Research Completed". Create "iphone" → 3 *different* vendors. Create a nonsense product → "Manual research".
   Check the logs show `feature=vendor_search` on `/vendor-search` and the vendor items' own triggers
   logged as ignored.
5. Promote the version.

**Rollback:** turn off the board automation (stops all runs immediately); if needed, remove the block or
promote the previous app version. No other feature depends on this one.

## 14. Risks and open points

| Risk | Handling |
| --- | --- |
| A person adds a vendor by hand in group 1 and leaves Search Source empty → the bot treats its name as a product | Team rule: set Search Source ("Inbound vendor", "Existing vendor", …) when adding a vendor by hand — or add the item with that value already chosen. To confirm with Sana. |
| Run lost if the server restarts mid-search (background thread, same as enrichment) | The request stays on **"AI Bot"** with no vendors. A request on "AI Bot" for more than ~30 minutes means the run was lost. To retry: create the request again. No queue for now. |
| AI quality varies by product (very generic or very niche names) | Germany gate + verification in code; local dry run on real products before deploy (step 6). |
| Time per request | A few minutes expected (3 checks in parallel); measured in the dry run. |
| Labels on the request side: the board shows "Request (name of item)", the API title is "Vendor" | Column ids are used, not titles, so it does not matter to the bot. |

### Change (2026-11-19): vendor rows named after the vendor
- The request row is renamed from the product to the best vendor's company name when it is filled
  (`name` key in `change_multiple_column_values`; kept on the core-columns retry).
- The 2nd and 3rd vendors are created with the vendor's company name (was: the product name).
- Nothing found: the request keeps its product name ("Manual research").
- The product stays in Product Categories, so the no-repeat-vendor check is unchanged.

### Change (2026-11-20): 2nd and 3rd vendors created in group 1, then moved to group 2
- Reason: the board automation "When item moves to group 2 -> Lifecycle Stage = ICP Scoring"
  (added 2026-11-19) ran only for the request row, which is moved; rows created straight in
  group 2 kept "Vendor Search Initiated".
- Now `create_vendor` creates in `topics` with Search Source "Research Completed" already set (so the
  item's own "item created" trigger does not start a search), then `move_item_to_group` -> `new_group`.
- A failed move is logged; the item stays in group 1. The request row is still never moved by the code.

### Change (2026-11-20): contact name and job title separated; job title linked to Job Functions
- The check prompt asks for `contact_person` (name only) and `contact_person_role` separately; a role still
  written into the name ("Name, Role" / "Name - Role" / "Name (Role)") is split off in code (`mapping.contact`).
- Name of Contact Person gets the name only.
- The role is linked in "Job Functions and Departments" (`board_relation_mm9685qm`, board 5108003087):
  written the same as a title on that board -> matched in code; otherwise one AI question without web search
  for all the run's titles (only titles from the board are accepted). No match -> the column stays empty.
- The Department mirror fills itself from the linked title. A failure here never stops the vendors.

### Change (2026-11-20): a second search round, so a request gets 3 vendors
- When the first step 1 search leaves fewer than 3 verified vendors, a second step 1 search runs, told
  every company already tried (and the board's vendors for the product) so it names new ones.
- Deep checks per request: 12 over both rounds (was 6). `FIND_ROUNDS = 2`, `MAX_CHECKS = 12`.
- All checks stay as strict as before; fewer than 3 only when two searches found no more that pass.
- A failed second round keeps the vendors already found. Industry / Main Industry / Sub Industry: not touched.

### Change (2026-11-20): full street address required
- Papernet passed with complete_address "München, Germany" because the postal code came in its own field.
- `matching.germany_problem` now also requires, in the address itself, a 5-digit postal code and a street
  with a house number (`STREET_AND_NUMBER`). Otherwise the company is rejected and the next candidate (or
  the second search round) replaces it.

## Change: Name of Product is a text column (2026-11-24)

- **Why:** the old **Name of Product** was the dropdown `dropdown_mm9512qn`, and every search added a
  new option to it (21 options by 24 Nov, including test values like "xyz").
- **Now:** the product is written as plain text into the new **Name of Product** text column
  `text_mm9dq3g3` (`settings.PRODUCT_NAME`). The no-repeat check reads the same column; a comma in a
  product name no longer splits it.
- **Removed:** reading the dropdown's option list (`product_labels`, `_dropdown_labels`). The same-product
  check now uses the product names written on the items (`product_names`).
- **Board:** the old dropdown was renamed "Name of Product (old)". Delete it only **after** this code is
  deployed. Rows created before the change have their product only in the old dropdown; copy them to the
  text column once, or they are not counted by the no-repeat check.

## Change: Product Category on every vendor row (2026-11-24)

- **Why:** "Product Catagory From Purchase Requirement" (`dropdown_mm9cm8vk`, `settings.PRODUCT_CATEGORY`)
  comes from the purchase requirement and was only on the request row; the 2nd and 3rd vendors had none.
- **Now:** when the vendors are written, the request's category is read (`monday.request_category`) and
  copied to every new vendor row. Read at that moment, not at the start, so a category set during the
  search is included. The request row itself is not rewritten.
- **No category on the request** (a request typed by hand, no purchase requirement): the AI picks one of
  the column's active options for the product (`research.pick_category`, one short question, no web
  search) and it is written to **all** vendor rows, the request included.
- **None of the options fits** (basketball got "Other"): the AI names a new broad category in the same
  style (e.g. "Sports & Leisure", at most `MAX_CATEGORY_LENGTH` characters, no comma, never the product
  name). It is created on the board (`create_labels_if_missing`) and offered to - so reused by - later
  searches. An unusable answer (empty, too long, a comma, the product name) or a failed question: no
  category. Reading the request's category fails: the AI is not asked either, so a
  category the request may have is never overwritten.
- **❌Purchase Request** (`text_mm9d22sk`) is never written by Vendor Search. Two board automations
  (1720152195, 1720154002: "when an item is created -> ❌Purchase Request = item name") fill it, also on
  the vendor rows Vendor Search creates in group 1.

## Change: the vendor's catalogue in Catalogue / Documents (2026-11-24)

- **What:** the deep check also asks for the vendor's own product catalogue (a PDF or catalogue page on
  its website, `catalogue_url`). It is added to **Catalogue / Documents** (`file_mm947aza`,
  `settings.CATALOGUE`) as a link named "Catalogue - <vendor>" with `update_assets_on_item`
  (file type `link`; a files column takes no value through `change_multiple_column_values`).
- **No catalogue -> product overview:** the AI lists up to `MAX_OVERVIEW_PRODUCTS` (50) products from the
  vendor's own website (`research.list_products`, one web-search call per vendor without a catalogue, all
  at the same time). `mapping.product_overview` keeps named products once, drops links to other sites;
  the list is uploaded as "Product overview (AI) - <vendor>.csv" (Product, Category, Link; UTF-8 with BOM
  for Excel) with `add_file_to_column` on `https://api.monday.com/v2/file` (`monday.upload_file`).
- **Never the product page:** neither a catalogue nor a product list -> the column stays empty.
  `mapping.catalogue` drops a link on another website and a link equal to the product page.
- **The request row:** the link is added only when its Catalogue / Documents column is empty, so a file
  attached by hand is never replaced. A failed link is logged; the vendor row is already written.
- **Cost:** the catalogue link needs no extra AI call (part of the deep check). A product overview is one
  extra web-search AI call per vendor without a catalogue (up to 3 per request, in parallel).
- **Every catalogue link is opened first** (`pages.catalogue_exists`, all at the same time). The first live
  run ("sticky paper") wrote three catalogue links the AI had invented - all 404. Now 404, blocked,
  timeout, an unknown host or a redirect to the home page all count as "no catalogue" (the vendor gets
  the product overview instead). The home page itself is never taken as a catalogue.
- **At least 30 products** (`MIN_OVERVIEW_PRODUCTS`), up to 50: the AI is asked for 30-50. Fewer than 30
  after cleaning: one more question for *other* products of the same website (the ones listed are named,
  so they are not repeated). Still fewer than 30: the vendor has no more, so the products found are
  attached (logged as `short_overviews`) - never padded with invented products. None at all: empty.
- **Catalogue order** (`service._resolve_catalogues`, all vendors at the same time): (1) the AI's catalogue
  link if it opens; (2) otherwise a catalogue linked on the vendor's home page, found by the code
  (`pages.find_catalogue`: a link whose address or text names a catalogue - Katalog, Catalogue,
  Broschüre, Brochure, Prospekt - on the vendor's own site, PDFs first, opened before use; no AI cost);
  (3) otherwise the product overview CSV. Found on the live board: the AI missed Sitwell's
  "Bürostuhl Gesamtkatalog 2026/27" PDF on its home page; (2) finds it.

## Change: the product overview CSV removed (2026-11-24)

- **Decision:** Catalogue / Documents gets **only a real catalogue**. The product overview CSV (AI listing
  30-50 products when there was no catalogue) is removed - `list_products`, `products_prompt`,
  `upload_file`, `product_overview(_csv)`, `MIN/MAX_OVERVIEW_PRODUCTS` and their tests are gone.
- **Now:** (1) the AI's catalogue link if it opens; (2) otherwise a catalogue linked on the vendor's home
  page (found by the code, opened first); (3) otherwise the column stays empty. The points above about
  the product overview no longer apply.
- **Effect:** no extra AI call per vendor and no extra minute; a search costs what it did before the
  catalogue feature, plus one home page load per vendor without a working AI link.
