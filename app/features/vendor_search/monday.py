"""
The monday API calls Vendor Search makes. Synchronous (requests): the search
runs on a background thread, like Company Enrichment.

  read_request(item_id)                          the request: name, board, group, Search Source
  request_category(item_id)                      the request's Product Category labels
  category_labels(board_id)                      the Product Category column's options
  set_search_source(board_id, item_id, label)    the request's progress
  board_vendors(board_id)                        every row: name, product name, website, legal name
  product_names(board_items)                     every product name on the board, once each
  fill_request(board_id, item_id, values, name)  the best vendor, into the request item (renamed to the vendor)
  create_vendor(board_id, name, values)          one new vendor item (the 2nd and 3rd): group 1, then moved to 2
  job_function_titles()                          the Job Functions board's titles: {title: item id}
  add_catalogue(board_id, item_id, link, name)   the vendor's catalogue link in Catalogue / Documents
  upload_file(item_id, file_name, content)       a file (the product overview) into Catalogue / Documents
"""
import json
import logging
import re

import requests

from . import settings

log = logging.getLogger('vendor_search')

API_URL = 'https://api.monday.com/v2'

# change_multiple_column_values renames the item with this key.
ITEM_NAME = 'name'


class MondayError(Exception):
    """monday answered with `errors`; kept whole so create_vendor can read which column it named."""

    def __init__(self, errors):
        super().__init__(json.dumps(errors, ensure_ascii=False)[:1000])
        self.errors = errors if isinstance(errors, list) else [errors]


def graphql(query, variables):
    res = requests.post(
        API_URL,
        json={'query': query, 'variables': variables},
        headers={
            'Authorization': settings.monday_token(),
            'API-Version': settings.monday_api_version(),
            'Content-Type': 'application/json',
        },
        timeout=60,
    )
    try:
        body = res.json() or {}
    except ValueError:
        res.raise_for_status()
        raise MondayError([{'message': f'HTTP {res.status_code}: not JSON'}])
    if body.get('errors') or body.get('error_message'):
        raise MondayError(body.get('errors') or [{'message': body.get('error_message')}])
    res.raise_for_status()
    return body.get('data') or {}


# ---- the request ----------------------------------------------------------------

REQUEST_QUERY = """
query ($itemId: [ID!], $columns: [String!]) {
  items(ids: $itemId) {
    id
    name
    board { id }
    group { id }
    column_values(ids: $columns) { id text }
  }
}
"""


def read_request(item_id):
    """{'id', 'name', 'board_id', 'group_id', 'search_source'}, or None when the item is gone."""
    data = graphql(REQUEST_QUERY, {'itemId': [str(item_id)], 'columns': [settings.SEARCH_SOURCE]})
    items = data.get('items') or []
    if not items:
        return None
    item = items[0]
    source = next((cv.get('text') for cv in item.get('column_values') or [] if cv.get('id') == settings.SEARCH_SOURCE), '')
    return {
        'id': str(item.get('id')),
        'name': str(item.get('name') or ''),
        'board_id': str((item.get('board') or {}).get('id') or ''),
        'group_id': str((item.get('group') or {}).get('id') or ''),
        'search_source': str(source or '').strip(),
    }


def request_category(item_id):
    """The request's Product Category labels (from the purchase requirement), [] when it has none."""
    data = graphql(REQUEST_QUERY, {'itemId': [str(item_id)], 'columns': [settings.PRODUCT_CATEGORY]})
    items = data.get('items') or []
    text = next((cv.get('text') for item in items for cv in item.get('column_values') or []
                 if cv.get('id') == settings.PRODUCT_CATEGORY), '')
    # A dropdown's text is its labels joined by ', ' (no category label has a comma).
    return [label.strip() for label in str(text or '').split(', ') if label.strip()]


CATEGORY_LABELS_QUERY = """
query ($boardId: [ID!], $columns: [String!]) {
  boards(ids: $boardId) { columns(ids: $columns) { id settings_str } }
}
"""


def category_labels(board_id):
    """The Product Category column's active options, in the column's order ([] when it has none)."""
    data = graphql(CATEGORY_LABELS_QUERY, {'boardId': [str(board_id)], 'columns': [settings.PRODUCT_CATEGORY]})
    columns = [column for board in data.get('boards') or [] for column in board.get('columns') or []]
    try:
        parsed = json.loads((columns[0] if columns else {}).get('settings_str') or '{}')
    except ValueError:
        return []
    off = set(parsed.get('deactivated_labels') or [])
    labels = parsed.get('labels') or []
    if isinstance(labels, dict):  # the older settings format: {"1": "name"}
        labels = [{'id': int(key), 'name': name} for key, name in labels.items() if str(key).isdigit()]
    return [str(label['name']) for label in labels
            if isinstance(label, dict) and label.get('name') and label.get('id') not in off]


SET_STATUS = """
mutation ($boardId: ID!, $itemId: ID!, $columnId: String!, $value: JSON!) {
  change_column_value(board_id: $boardId, item_id: $itemId, column_id: $columnId, value: $value) { id }
}
"""


def set_search_source(board_id, item_id, label):
    graphql(SET_STATUS, {
        'boardId': str(board_id),
        'itemId': str(item_id),
        'columnId': settings.SEARCH_SOURCE,
        'value': json.dumps({'label': label}),
    })



# ---- vendors already on the board ---------------------------------------------------

ITEMS_QUERY = """
query ($boardId: ID!, $cursor: String, $columns: [String!]) {
  boards(ids: [$boardId]) {
    items_page(limit: 500, cursor: $cursor) {
      cursor
      items { id name column_values(ids: $columns) { id text } }
    }
  }
}
"""

URL_IN_TEXT = re.compile(r'https?://\S+', re.IGNORECASE)


def board_vendors(board_id):
    """Every item with its product name, website and legal name, following the cursor to the end."""
    items, cursor = [], None
    columns = [settings.PRODUCT_NAME, settings.WEBSITE, settings.LEGAL_NAME]
    for _page in range(40):  # bounded: a cursor that never ends cannot spin forever
        data = graphql(ITEMS_QUERY, {'boardId': str(board_id), 'cursor': cursor, 'columns': columns})
        boards = data.get('boards') or []
        page = (boards[0] if boards else {}).get('items_page') or {}
        for item in page.get('items') or []:
            columns = {cv.get('id'): cv.get('text') or '' for cv in item.get('column_values') or []}
            website = columns.get(settings.WEBSITE, '')
            link = URL_IN_TEXT.search(website)
            product = columns.get(settings.PRODUCT_NAME, '').strip()
            items.append({
                'id': str(item.get('id')),
                'name': str(item.get('name') or ''),
                'products': [product] if product else [],
                'website': link.group(0) if link else website,
                'legal_name': columns.get(settings.LEGAL_NAME, ''),
            })
        cursor = page.get('cursor')
        if not cursor:
            break
    return items


JOB_TITLES_QUERY = """
query JobTitles($boardId: ID!, $cursor: String) {
  boards(ids: [$boardId]) {
    items_page(limit: 500, cursor: $cursor) { cursor items { id name } }
  }
}
"""


ADD_CATALOGUE = """
mutation ($boardId: ID!, $itemId: ID!, $columnId: String!, $files: [FileInput!]!) {
  update_assets_on_item(board_id: $boardId, item_id: $itemId, column_id: $columnId, files: $files) { id }
}
"""


def has_files(item_id):
    """True when the item's Catalogue / Documents column already holds a file or link."""
    data = graphql(REQUEST_QUERY, {'itemId': [str(item_id)], 'columns': [settings.CATALOGUE]})
    return any((cv.get('text') or '').strip() for item in data.get('items') or []
               for cv in item.get('column_values') or [] if cv.get('id') == settings.CATALOGUE)


def add_catalogue(board_id, item_id, link, name):
    """The catalogue as a link in Catalogue / Documents (a files column takes links as file type "link")."""
    graphql(ADD_CATALOGUE, {
        'boardId': str(board_id), 'itemId': str(item_id), 'columnId': settings.CATALOGUE,
        'files': [{'fileType': 'link', 'name': name, 'linkToFile': link}],
    })


FILE_URL = 'https://api.monday.com/v2/file'

ADD_FILE = """
mutation ($file: File!, $itemId: ID!, $columnId: String!) {
  add_file_to_column(item_id: $itemId, column_id: $columnId, file: $file) { id }
}
"""


def upload_file(item_id, file_name, content, content_type='text/csv'):
    """One file into Catalogue / Documents, through monday's file endpoint (a multipart request)."""
    res = requests.post(
        FILE_URL,
        data={'query': ADD_FILE, 'variables': json.dumps({'itemId': str(item_id), 'columnId': settings.CATALOGUE})},
        files={'variables[file]': (file_name, content, content_type)},
        headers={'Authorization': settings.monday_token(), 'API-Version': settings.monday_api_version()},
        timeout=60,
    )
    try:
        body = res.json() or {}
    except ValueError:
        res.raise_for_status()
        raise MondayError([{'message': f'HTTP {res.status_code}: not JSON'}])
    if body.get('errors') or body.get('error_message'):
        raise MondayError(body.get('errors') or [{'message': body.get('error_message')}])
    res.raise_for_status()
    return body.get('data') or {}


def job_function_titles():
    """Every title on the Job Functions board as {title: item id}; a title listed twice keeps its first item."""
    titles, cursor = {}, None
    for _page in range(10):
        data = graphql(JOB_TITLES_QUERY, {'boardId': str(settings.JOB_FUNCTIONS_BOARD), 'cursor': cursor})
        boards = data.get('boards') or []
        page = (boards[0] if boards else {}).get('items_page') or {}
        for item in page.get('items') or []:
            name = str(item.get('name') or '').strip()
            if name and name not in titles:
                titles[name] = int(item['id'])
        cursor = page.get('cursor')
        if not cursor:
            break
    return titles


def product_names(board_items):
    """Every product name written on the board's items, once each, in board order."""
    return list(dict.fromkeys(name for item in board_items for name in item.get('products') or [] if name))


# ---- writing a vendor: the request itself, or a new item ------------------------------

CREATE_ITEM = """
mutation ($boardId: ID!, $groupId: String!, $name: String!, $values: JSON!) {
  create_item(board_id: $boardId, group_id: $groupId, item_name: $name,
              column_values: $values, create_labels_if_missing: true) { id }
}
"""

FILL_ITEM = """
mutation ($boardId: ID!, $itemId: ID!, $values: JSON!) {
  change_multiple_column_values(board_id: $boardId, item_id: $itemId,
                                column_values: $values, create_labels_if_missing: true) { id }
}
"""


def _rejected_column(error):
    """The column id monday named in a ColumnValueException, or None."""
    for entry in error.errors:
        extensions = (entry or {}).get('extensions') or {}
        data = extensions.get('error_data') or {}
        column = data.get('column_id') or (entry or {}).get('column_id')
        if column:
            return str(column)
    return None


def _write(label, values, send):
    """
    Sends the vendor's column values with send(payload); returns (send's result, dropped column ids).

    A column monday rejects by name is dropped and the write retried. A rejection
    that names no column (monday did that for Company Enrichment's email) is
    retried once with only the core columns. Search Source is never dropped.
    """
    payload, dropped, core_only = dict(values), [], False
    for _attempt in range(len(values) + 2):
        try:
            return send(payload), dropped
        except MondayError as error:
            column = _rejected_column(error)
            if column and column in payload and column != settings.SEARCH_SOURCE:
                log.warning(f'monday rejected column {column} for {label} - dropping it and retrying',
                            extra={'payload': {'column_id': column, 'errors': error.errors}})
                dropped.append(column)
                del payload[column]
                continue
            if not column and not core_only:
                core = {key: value for key, value in payload.items()
                        if key in settings.CORE_COLUMNS or key == ITEM_NAME}
                dropped.extend(key for key in payload if key not in core)
                log.warning(f'monday rejected {label} without naming a column - retrying with core columns only',
                            extra={'payload': {'errors': error.errors}})
                payload, core_only = core, True
                continue
            raise
    raise MondayError([{'message': f'{label}: too many rejected columns'}])


def fill_request(board_id, item_id, values, name=None):
    """
    Writes the best vendor into the request item itself and renames the item to
    the vendor (`name`); returns (item_id, dropped column ids).
    """
    if name:
        values = {ITEM_NAME: name, **values}

    def send(payload):
        graphql(FILL_ITEM, {'boardId': str(board_id), 'itemId': str(item_id),
                            'values': json.dumps(payload, ensure_ascii=False)})
        return str(item_id)

    return _write(f'request item {item_id}', values, send)


MOVE_ITEM = """
mutation ($itemId: ID!, $groupId: String!) {
  move_item_to_group(item_id: $itemId, group_id: $groupId) { id }
}
"""


def create_vendor(board_id, name, values):
    """
    Creates a vendor item in group 1 and moves it to group 2; returns (item_id, dropped column ids).

    The move - not a create straight into group 2 - is what runs the board's
    "When item moves to group 2" automation (Lifecycle Stage -> ICP Scoring), the
    same as for the request row. Search Source is set at creation, so the item's
    own "item created" trigger does not start a search. If the move fails the item
    stays in group 1 (logged).

    `name` is the item name - the vendor's company name.
    """
    def send(payload):
        data = graphql(CREATE_ITEM, {
            'boardId': str(board_id), 'groupId': settings.REQUEST_GROUP_ID,
            'name': name, 'values': json.dumps(payload, ensure_ascii=False),
        })
        return str((data.get('create_item') or {}).get('id') or '')

    item_id, dropped = _write(f'new vendor item "{name}"', values, send)
    try:
        graphql(MOVE_ITEM, {'itemId': item_id, 'groupId': settings.DONE_GROUP_ID})
    except (MondayError, requests.RequestException) as error:
        log.error(f'Vendor item {item_id} "{name}" was created but not moved to group 2: {error}',
                  extra={'payload': {'item_id': item_id, 'error': str(error)}})
    return item_id, dropped
