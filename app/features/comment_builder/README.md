# comment_builder

**Item View** "Comment Builder" of the Company Management app (11727119): log a
comment on a deal, with three AI helpers. Moved here from the separate Comment
Builder app (11942098), which is retired once every board uses this view.

| Button | Route | OpenAI |
| --- | --- | --- |
| ✍️ Write with AI | `POST /api/ai/write` `{prompt}` → `{text}` | drafts a CRM update |
| 📋 Summarize | `POST /api/ai/summarize` `{text}` → `{text}` | 2–4 bullets from an update |
| ✨ Autofill | `POST /api/ai/autofill` `{comment, options, …}` → `{fields}` | the comment form's fields, by the team's category rules |
| 📎 From Computer | `POST /api/files/upload?updateId=&itemId=&name=`, body = the file → `{id, name, url}` | — (monday's file API) |

```
router.py     the page, its assets, the AI routes, the upload route, /comment-builder/health
service.py    write / summarize / autofill: the prompts and AUTOFILL_GUIDE (the team's rules), OpenAI
files.py      upload: checks the update is the user's, then add_file_to_update on monday's file API
ratelimit.py  30 calls a minute per user (AI and uploads apart) and per IP
schemas.py    request/response models
page/         the page's sources and build.py → static/
static/       the built page - served byte for byte, never edited by hand
tests/
```

**Files from the computer** work like monday's own Updates editor: the file becomes a
link in the update's text (`…monday.com/protected_static/…`, which downloads it) and
is attached to the update. monday attaches files only to an update that exists, so
the page posts the update with a placeholder link, uploads each file to it, then
puts the real link in. Up to 25 MB per file. The server uploads with
`MONDAY_API_TOKEN` (monday shows that token's user as the file's uploader; the
update's author stays the user) and only after monday confirms the update, or
reply, is on that item and was written by the session's user. A file that fails is
left as plain text in the update and named in a note.

Unlike the automation blocks, this is a page in monday's iframe:

- **The page is public** (`GET /comment-builder`, `/assets/*`): the iframe loads it with no token.
- **The AI routes check monday's session token** (`app/core/security.py::verify_session_token`):
  HS256 with the app's **Client Secret**, `exp`, and `dat.app_id` = this app. Not the Signing Secret.
- **Errors are `{"error": "…"}`** (`app/core/views.py`): the page shows `error`.

The prompts, `AUTOFILL_GUIDE`, limits and messages are the original server's,
with one change (2026-11-03): Autofill classified frei Haus / VAT comments on a
"Quote In Progress" deal as Quote. `AUTOFILL_GUIDE` now says the deal stage is
never the topic and that a frei Haus threshold is ORDER (TAX with MwSt.), with
two more examples, and Catagories is derived from the main category in code.
The comment, prompt, update text and AI answers are never logged.

## On monday

Developer Center → Company Management → the version under test → Features →
**Create feature → Item View** `Comment Builder`:

- Deployment: **monday code** (this deployment), route `/comment-builder`
- Permissions (OAuth scopes): the ones the old Comment Builder app has - the page reads
  items, updates and users, and creates and edits updates.

Then on each board: open an item → **+** → Comment Builder (Company Management).

## Settings

| Key | |
| --- | --- |
| `OPENAI_API_KEY` | required (the same key Company Enrichment uses) |
| `MONDAY_CLIENT_SECRET` | required: Company Management → **Basic Information → Client Secret**. Without it every AI call is refused |
| `MONDAY_API_TOKEN` | required for uploads (shared with the other features). Its user needs access to the boards |
| `MONDAY_APP_ID` | optional, default `11727119` |
| `COMMENT_BUILDER_OPENAI_MODEL` | optional, default `gpt-4o-mini`. Not `OPENAI_MODEL`: that is Company Enrichment's |

After a deploy, open `<deployment URL>/comment-builder/health`: `signatureCheck`
must be `on` and both secrets found (their source only, never a value).

## Changing the page

Edit the sources in `page/`, then rebuild `static/`:

```bash
python3 -I app/features/comment_builder/page/build.py
```

`page/` holds the original v2 bundle from monday (`base/`, never edited) and the
four files swapped into it (`comment-logic.js`, `updates-feed.js`, `ui.js`,
`updates.css`). They came from the old Comment Builder project's `v4/` with
`v4-fixes.diff` applied (photo field, double mention, Autofill), and rebuilt the
page that was live byte for byte before the upload was added (2026-11-03).
`tests/test_page.py` fails if `static/` is not built from the current
`updates-feed.js`.

The page asks for `/assets/…` and `/api/…` by absolute path, which is why those
routes are at the root.
