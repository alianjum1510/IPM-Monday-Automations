# vendor_name_split

Automation block **Vendor Name Split** on the **Vendors** board (`5094193564`):

```
"Vendor Name Split for {Item id} in {board id}"   POST /vendor-name-split
```

| Column | Id | |
|---|---|---|
| Vendors (the item name) | `name` | read only, never changed |
| Vendor Name Part 1 | `text_mkt92ar9` | up to `MAX_NAME_LENGTH` (100) characters, cut at a word |
| Vendor Name Part 2 | `text_mksb1npw` | the rest; **emptied** when the name fits |

The split rule is the shared one in `app/core/name_split.py` (same as Customer
Name Split). Only the parts whose value changes are written, so a re-run - or a
trigger fired by the app's own write - does nothing.

```
router.py    POST /vendor-name-split: reads boardId / itemId, calls the service
service.py   split_vendor_name(): read name + parts, split, write what changed
schemas.py   response models
tests/
```

## On monday
- Developer Center → Company_enrichment → the version under test → Features →
  **Automation block** `Vendor Name Split`: Action, async off, inputs `boardId`
  (`board id`) and `itemId` (`Item id`) from Sentence, sentence
  `Vendor Name Split for {Item id} in {board id}`, Execution URL
  `<deployment URL>/vendor-name-split`.
- Vendors board automations: **When an item is created** and **When item name
  changes** → Company_enrichment → **Vendor Name Split**.

Settings: `MONDAY_API_TOKEN` (and the shared `MONDAY_SIGNING_SECRET` /
`MONDAY_JWT_AUDIENCE_*`). Optional: `MAX_NAME_LENGTH`.
