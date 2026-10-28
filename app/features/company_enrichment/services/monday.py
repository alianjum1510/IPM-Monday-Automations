import json

import requests

from app.features.company_enrichment.config.env import env
from app.features.company_enrichment.lib.logger import log


class GraphQLError(Exception):
    """monday answered, but with `errors` - kept whole so write_columns can read which column it named."""

    def __init__(self, errors):
        super().__init__(json.dumps(errors))
        self.graphql_errors = errors


def graphql(query, variables=None):
    res = requests.post(
        env.monday.api_url,
        json={'query': query, 'variables': variables or {}},
        headers={
            'Content-Type': 'application/json',
            'Authorization': env.monday.api_token,
            'API-Version': env.monday.api_version,
        },
        timeout=60,
    )
    res.raise_for_status()

    data = res.json() or {}
    if data.get('errors'):
        raise GraphQLError(data['errors'])

    return data.get('data')


ITEM_QUERY = """
  query Item($itemId: [ID!]) {
    items(ids: $itemId) {
      id
      name
      state
      board { id }
      column_values { id text }
    }
  }
"""

BOARD_COLUMNS_QUERY = """
  query BoardColumns($boardId: [ID!]) {
    boards(ids: $boardId) {
      id
      name
      columns { id title type settings_str }
    }
  }
"""

# The items of a connected board, for the board_relation columns.
#
# Paginated deliberately: the Job Function taxonomy already holds 197 items and
# a single `limit: 200` page would silently start losing the tail as the board
# grows. A truncated taxonomy does not error - it just stops matching - so this
# follows the cursor to the end.
BOARD_ITEMS_QUERY = """
  query BoardItems($boardId: ID!, $cursor: String) {
    boards(ids: [$boardId]) {
      id
      items_page(limit: 500, cursor: $cursor) {
        cursor
        items { id name }
      }
    }
  }
"""

# `create_labels_if_missing: false` is the backstop for the controlled
# columns: status and dropdown values are already written by index / id
# against options the board has, and if anything ever slips through as a
# label string, monday rejects that one column (write_columns drops it and
# retries) instead of adding an option nobody created.
CHANGE_VALUES = """
  mutation ChangeValues($boardId: ID!, $itemId: ID!, $values: JSON!) {
    change_multiple_column_values(
      board_id: $boardId
      item_id: $itemId
      column_values: $values
      create_labels_if_missing: false
    ) { id }
  }
"""


def get_board(board_id):
    data = graphql(BOARD_COLUMNS_QUERY, {'boardId': [str(board_id)]})
    boards = (data or {}).get('boards') or []
    if not boards:
        raise Exception(f'Board {board_id} not found or not accessible')
    return boards[0]


def get_item(item_id):
    data = graphql(ITEM_QUERY, {'itemId': [str(item_id)]})
    items = (data or {}).get('items') or []
    return items[0] if items else None


def get_board_items(board_id):
    """Every item on a board, following the cursor to the end."""
    items = []
    cursor = None

    # Bounded so a cursor that never terminates cannot spin forever.
    for _page in range(40):
        data = graphql(BOARD_ITEMS_QUERY, {'boardId': str(board_id), 'cursor': cursor})
        boards = (data or {}).get('boards') or []
        items_page = boards[0].get('items_page') if boards else None
        if not items_page:
            break

        for item in items_page.get('items') or []:
            items.append({'id': str(item['id']), 'name': str(item.get('name') or '')})

        cursor = items_page.get('cursor')
        if not cursor:
            return items

    return items


def write_columns(board_id, item_id, values):
    """
    Writes the columns.

    change_multiple_column_values is all-or-nothing, so a single column monday
    dislikes would sink the whole update. When it comes back with a
    ColumnValueException naming a column, that column is dropped and the rest is
    retried - a bad phone number costs one column, not the enrichment.

    Returns {'written': n, 'dropped': [column ids]}.
    """
    payload = dict(values)
    dropped = []

    # Generous ceiling: an N/A fill monday dislikes costs one attempt per column.
    for _attempt in range(14):
        if not payload:
            return {'written': 0, 'dropped': dropped}

        try:
            graphql(CHANGE_VALUES, {
                'boardId': str(board_id),
                'itemId': str(item_id),
                'values': json.dumps(payload, ensure_ascii=False),
            })
            return {'written': len(payload), 'dropped': dropped}
        except GraphQLError as error:
            first = error.graphql_errors[0] if error.graphql_errors else {}
            details = ((first or {}).get('extensions') or {}).get('error_data') or {}
            bad_column = details.get('column_id')

            if details.get('inactive_pulse_ids'):
                raise Exception(f'item {item_id} is inactive (deleted or archived)')

            if bad_column and bad_column in payload:
                log(f'Item {item_id}: monday rejected column {bad_column} - dropping and retrying')
                dropped.append(bad_column)
                del payload[bad_column]
                continue

            raise

    raise Exception('too many rejected columns')
