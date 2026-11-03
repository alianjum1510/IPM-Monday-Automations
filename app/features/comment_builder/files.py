"""
Attach a file to a monday update - the page's 📎 "From Computer".

monday's own Updates editor uploads a file and puts a link to it in the text. The page does the same: it posts
the update, then sends each file here with the update's id, and puts the returned link
(https://<account>.monday.com/protected_static/…, which downloads the file) in the update's text.

The page can't do the upload itself (the SDK's api() takes no files), so this server does, with
MONDAY_API_TOKEN, through monday's file endpoint (add_file_to_update). Before it does, it asks monday whether
the update - or reply - is on that item and was written by the session's user: a user attaches files only to
their own updates.

Synchronous (urllib, like service.py): the router runs it in the thread pool.
"""
import json
import urllib.error
import urllib.request
import uuid

from app.core.monday_client import api_version
from app.core.views import ViewError

API_URL = "https://api.monday.com/v2"
FILE_URL = "https://api.monday.com/v2/file"
TIMEOUT_SECONDS = 120
UPDATES_CHECKED = 100  # the page shows the item's latest 50 updates

UPDATES_QUERY = """query ($itemId: [ID!]) {
  items (ids: $itemId) { updates (limit: %d) { id creator_id replies { id creator_id } } }
}""" % UPDATES_CHECKED


def call(req):
    """monday's JSON answer; HTTP or GraphQL errors become ViewError(502) with monday's message."""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
            raw = res.read()
    except urllib.error.HTTPError as e:
        raw = e.read()
    except urllib.error.URLError as e:
        raise ViewError(502, f"monday could not be reached: {e.reason}") from e
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    errors = data.get("errors") or data.get("error_message")
    if errors or not isinstance(data.get("data"), dict):
        message = "; ".join(e.get("message", "") for e in errors if isinstance(e, dict)) if isinstance(errors, list) else errors
        raise ViewError(502, f"monday API error: {message or 'no answer'}")
    return data["data"]


def headers(token, content_type):
    return {"Authorization": token, "API-Version": api_version(), "Content-Type": content_type}


def check_author(token, item_id, update_id, user_id):
    """The update (or reply) is on the item and was written by user_id - else ViewError 404 / 403."""
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": UPDATES_QUERY, "variables": {"itemId": [item_id]}}).encode("utf-8"),
        headers=headers(token, "application/json"),
        method="POST",
    )
    items = call(req).get("items") or [{}]
    updates = (items[0] or {}).get("updates") or []
    found = next(
        (u for top in updates for u in (top, *(top.get("replies") or [])) if str(u.get("id")) == update_id),
        None,
    )
    if not found:
        raise ViewError(404, "This update was not found on this item.")
    if str(found.get("creator_id")) != str(user_id):
        raise ViewError(403, "You can attach files only to your own updates.")


def multipart(fields, file_field, file_name, content, content_type):
    """multipart/form-data body and its Content-Type, for monday's file endpoint."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def safe_name(name):
    """The file name as a quoted header value: no quotes, line breaks or path."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(" " if c in '\r\n"' or ord(c) < 32 else c for c in name).strip()
    return name[:255]


def attach(token, item_id, update_id, user_id, name, content, content_type):
    """Upload `content` to the update after check_author. {id, name, url} of monday's new asset."""
    check_author(token, item_id, update_id, user_id)
    # update_id is digits only (checked by the router), so it can be written into the query.
    query = f"mutation ($file: File!) {{ add_file_to_update (update_id: {update_id}, file: $file) {{ id name url }} }}"
    body, form_type = multipart({"query": query}, "variables[file]", name, content, content_type)
    req = urllib.request.Request(FILE_URL, data=body, headers=headers(token, form_type), method="POST")
    asset = call(req).get("add_file_to_update") or {}
    if not asset.get("url"):
        raise ViewError(502, "monday did not return a link to the file.")
    return {"id": str(asset.get("id") or ""), "name": asset.get("name") or name, "url": asset["url"]}
