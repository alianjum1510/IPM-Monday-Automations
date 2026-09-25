import axios from 'axios';
import { env } from '../config/env.js';
import { log } from '../lib/logger.js';

const client = axios.create({
  baseURL: env.monday.apiUrl,
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
});

export async function graphql(query, variables = {}) {
  const res = await client.post(
    '',
    { query, variables },
    {
      headers: {
        Authorization: env.monday.apiToken,
        'API-Version': env.monday.apiVersion,
      },
    },
  );

  if (res.data?.errors?.length) {
    const error = new Error(JSON.stringify(res.data.errors));
    error.graphQLErrors = res.data.errors;
    throw error;
  }

  return res.data?.data;
}

const ITEM_QUERY = `
  query Item($itemId: [ID!]) {
    items(ids: $itemId) {
      id
      name
      state
      board { id }
      column_values { id text }
    }
  }
`;

const BOARD_COLUMNS_QUERY = `
  query BoardColumns($boardId: [ID!]) {
    boards(ids: $boardId) {
      id
      name
      columns { id title type settings_str }
    }
  }
`;

/**
 * The items of a connected board, for the board_relation columns.
 *
 * Paginated deliberately: the Job Function taxonomy already holds 197 items and
 * a single `limit: 200` page would silently start losing the tail as the board
 * grows. A truncated taxonomy does not error - it just stops matching - so this
 * follows the cursor to the end.
 */
const BOARD_ITEMS_QUERY = `
  query BoardItems($boardId: ID!, $cursor: String) {
    boards(ids: [$boardId]) {
      id
      items_page(limit: 500, cursor: $cursor) {
        cursor
        items { id name }
      }
    }
  }
`;

const CHANGE_VALUES = `
  mutation ChangeValues($boardId: ID!, $itemId: ID!, $values: JSON!) {
    change_multiple_column_values(
      board_id: $boardId
      item_id: $itemId
      column_values: $values
      create_labels_if_missing: true
    ) { id }
  }
`;

export async function getBoard(boardId) {
  const data = await graphql(BOARD_COLUMNS_QUERY, { boardId: [String(boardId)] });
  const board = data?.boards?.[0];
  if (!board) throw new Error(`Board ${boardId} not found or not accessible`);
  return board;
}

export async function getItem(itemId) {
  const data = await graphql(ITEM_QUERY, { itemId: [String(itemId)] });
  return data?.items?.[0] || null;
}

/** Every item on a board, following the cursor to the end. */
export async function getBoardItems(boardId) {
  const items = [];
  let cursor = null;

  // Bounded so a cursor that never terminates cannot spin forever.
  for (let page = 0; page < 40; page += 1) {
    const data = await graphql(BOARD_ITEMS_QUERY, { boardId: String(boardId), cursor });
    const itemsPage = data?.boards?.[0]?.items_page;
    if (!itemsPage) break;

    for (const item of itemsPage.items || []) {
      items.push({ id: String(item.id), name: String(item.name || '') });
    }

    cursor = itemsPage.cursor;
    if (!cursor) return items;
  }

  return items;
}

/**
 * Writes the columns.
 *
 * change_multiple_column_values is all-or-nothing, so a single column monday
 * dislikes would sink the whole update. When it comes back with a
 * ColumnValueException naming a column, that column is dropped and the rest is
 * retried - a bad phone number costs one column, not the enrichment.
 */
export async function writeColumns(boardId, itemId, values) {
  let payload = { ...values };
  const dropped = [];

  // Generous ceiling: an N/A fill monday dislikes costs one attempt per column.
  for (let attempt = 0; attempt < 14; attempt += 1) {
    if (Object.keys(payload).length === 0) return { written: 0, dropped };

    try {
      await graphql(CHANGE_VALUES, {
        boardId: String(boardId),
        itemId: String(itemId),
        values: JSON.stringify(payload),
      });
      return { written: Object.keys(payload).length, dropped };
    } catch (error) {
      const details = error.graphQLErrors?.[0]?.extensions?.error_data;
      const badColumn = details?.column_id;

      if (details?.inactive_pulse_ids?.length) {
        throw new Error(`item ${itemId} is inactive (deleted or archived)`);
      }

      if (badColumn && badColumn in payload) {
        log(`Item ${itemId}: monday rejected column ${badColumn} - dropping and retrying`);
        dropped.push(badColumn);
        delete payload[badColumn];
        continue;
      }

      throw error;
    }
  }

  throw new Error('too many rejected columns');
}
