# Vendor Search

An automation block on the **Vendor Mining Board** (`5107912125`). A user creates an item in group
**"1. Vendor Search in Progress"** whose name is a **product** ("iPhone"). The bot finds up to **3 vendors
based in Germany** that sell exactly that product and creates one item per vendor in the same group.

Full design and decisions: [PLAN-vendor-search.md](../../../PLAN-vendor-search.md).

## The block

| | |
| --- | --- |
| Sentence | Vendor Search for {Item} in {Board} |
| Input fields | `itemId`, `boardId` (same as Company Enrichment) |
| Route | `POST /vendor-search` |
| Automation | **When an item is created** → Vendor Search |
| Answer | `{"outputFields": {}}` at once; the search runs on a background thread |

## What one run does

1. Reads the item. Stops (logs why) if the board isn't in `settings.BOARDS`, the item isn't in group
   `topics`, Search Source already has a value, or the item is already being searched.
2. Request **Search Source → "AI Bot"**.
3. Reads the vendors already on the board for the **same product, however it was written**. They are
   never returned again; a vendor found for a *different* product may be.
   - Same apart from case, spaces, hyphens ("Euro pallets" = "europallets" = "Euro-Pallets"): decided in code.
   - A typo, plural or translation ("eurppallets", "Euro pallet", "Europaletten"): one short AI question
     without web search, answered only with labels already on the board. A different model, size or
     variant stays a different product ("iPhone 15" ≠ "iPhone").
   - The existing Product Categories label is reused, so one product keeps one label.
4. **Step 1, find** (1 AI call, web search): up to 10 German candidates.
5. **Step 2, check** (1 AI call each, 3 at a time): Impressum, register, VAT, address, contacts. A vendor
   is kept only if it is confirmed to sell the exact product **and** passes the Germany check in code
   (street and house number plus German 5-digit postal code in the address, city, address source URL,
   nothing foreign in the address). A failure is
   replaced by the next candidate. Fewer than 3 after the first search: a second search for new companies
   (told who was already tried); at most 12 checks per request.
6. Ranks the checked vendors (verified data → manufacturer/distributor → established → reachable) and
   writes the best 3:
   - the **best one into the request item itself** (so no empty request row is left);
   - the **other two as new items**: created in group 1, then **moved** to **2. Criteria Check & ICP Scoring**
     (the move runs the board's "item moves to group 2" automation, as for the request row).

   Every vendor row is **named after the vendor** (the request row is renamed from the product to the
   best vendor), with the company in **Legal Company Name**, the product in Product Categories, and Search Source
   **"Research Completed"**. Repeats are recognised by Legal Company Name and website.
7. Nothing found (or the AI failed after 3 retries, or any error): the request gets **"Manual research"**
   and **stays in group 1** with its product name, empty, for manual research.

The code never moves the request. The board automation "Search Source changes to Research Completed →
move to group 2" does: with it on, a completed request goes to group 2; without it, it stays in group 1.

A field the AI can't find is left empty: never guessed, never "N/A".

**Product page check** ([pages.py](pages.py)): the code opens the page the AI gives as proof. The vendor
is rejected (and replaced by the next candidate) when that page is on another website (a marketplace),
doesn't exist (404 / unknown host), or mentions neither the request's words nor the word the AI says the
page uses for the product. This stops invented products (gpt-4o-mini described a "zzqlorp 8812 fuel
pump"). A page that is blocked, too slow or built by JavaScript can't be read, and is not rejected.

**Company Size** is the number published (250), or the middle of a published range ("51-200" → 126).
**Deleiver Regions**: all 16 states listed one by one become "Bundesweit".

## Files

| File | |
| --- | --- |
| `settings.py` | `SEARCH_AREA`, board, group, column ids, labels, region list, limits |
| `router.py` | the route |
| `service.py` | the run; `select()` = find + check + rank, no writes |
| `research.py`, `prompts.py` | the two OpenAI calls (Responses API + web_search), retries |
| `matching.py` | same product, repeat vendors, the Germany check |
| `pages.py` | the product page check (opens the AI's proof page) |
| `mapping.py` | vendor → column values, validation of every value |
| `monday.py` | read request, read existing vendors, create item (with column-drop retry), set status |
| `dry_run.py` | the real search, printed, nothing written |

## Settings

Required: `MONDAY_API_TOKEN`, `OPENAI_API_KEY` (and the shared `MONDAY_SIGNING_SECRET`), all already on the
app. Optional: `VENDOR_SEARCH_MODEL` (else `OPENAI_MODEL`, else `gpt-4o`), `OPENAI_TIMEOUT_MS`,
`MONDAY_API_VERSION`.

To search somewhere other than Germany, change `SEARCH_AREA*` and the region list in `settings.py`.
To run on another board (e.g. production), add it to `BOARDS` after checking its column ids.

## Test

```
pytest app/features/vendor_search                 # all mocked, no real board or OpenAI
MONDAY_API_TOKEN=... OPENAI_API_KEY=... python -m app.features.vendor_search.dry_run "iPhone"
```

The dry run calls OpenAI for real (about the cost of a real run) but writes nothing to monday.

## Contact person and Job Functions

- **Name of Contact Person** gets the contact's name only.
- The contact's job title is linked in **Job Functions and Departments** (a connect-boards column to the
  board of the same name). A title written the same as on that board ("Geschäftsführer") is matched in
  code; another language or wording ("Managing Director", "CEO") by one short AI question without web
  search. No matching title: the column stays empty. **Department** (a mirror) then fills itself.

