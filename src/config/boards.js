import { log } from '../lib/logger.js';

/**
 * The boards this block runs on, by board id.
 *
 * Every board is enriched the same way: columns are resolved by TITLE and each
 * dropdown's options are read from the board the item lives on, so the
 * original and the dev copy each use their own options.
 *
 * `allowed` narrows that further: per column title, the ONLY values the AI may
 * be offered and that may be written. Options the board has but the list does
 * not name (old English duplicates such as "Landline") are invisible to the run.
 * A column with no list keeps all of its board options. A value on the list
 * that the board does not have is ignored and logged - nothing is ever created.
 */
export const BOARDS = {
  5100825258: { environment: 'Netgains sandbox', name: 'Warm Lead Mining Board' },
  5106281544: {
    environment: 'Dev sandbox',
    name: 'Warm Lead Mining Board (Copy)',
    /**
     * The dev sandbox dropdowns as they stand (screenshots and API, 2026-10-26).
     * The English entries marked below are duplicates an older build created;
     * delete a line here and the AI can no longer pick that value on dev.
     */
    allowed: {
      'Estimated Annual Revenue': [
        '< 1M EUR', '1M-10M EUR', '10M-50M EUR', '50M-100M EUR', '100M-500M EUR', '500M+ EUR', 'N/A',
      ],
      'Company Structure': [
        'Einzelgesellschaft', 'Holdinggesellschaft', 'Muttergesellschaft', 'Tochtergesellschaft',
        'Zweigniederlassung', 'Joint Venture', 'Partnergesellschaft', 'GmbH & Co. KG', 'N/A',
      ],
      'Ownership Type': [
        'Privatunternehmen', 'Öffentliche Institution', 'Gemeinnützige Organisation', 'Genossenschaft', 'N/A',
        'Private', // English duplicate
        'Municipality', // English duplicate
      ],
      'Phone Type': [
        'Festnetznummer', 'Mobilnummer', 'Andere', 'N/A',
        'Landline', // English duplicate
        'Mobile', // English duplicate
        'VoIP', // English
      ],
    },
  },
  5100463291: { environment: 'Netgains sandbox', name: 'Lead Mining Board' },
};

/** "Dev sandbox - Warm Lead Mining Board (Copy)", for the run log. */
export function describeBoard(boardId) {
  const board = BOARDS[String(boardId)];
  if (board) return `${board.environment} - ${board.name}`;
  return `board ${boardId} is not in src/config/boards.js - enriching it by column titles anyway`;
}

const same = (a, b) => String(a).trim().toLowerCase() === String(b).trim().toLowerCase();

/**
 * The board's columns with every listed dropdown cut down to its `allowed`
 * values. Everything downstream - the options in the prompt, the matching, the
 * N/A fill, the revenue bands - reads the options from these columns, so a
 * value missing from the list can be neither offered nor written.
 */
export function restrictToAllowedOptions(boardId, columns) {
  const allowed = BOARDS[String(boardId)]?.allowed || {};

  return columns.map((column) => {
    const list = allowed[column.title];
    if (!list?.length || (column.type !== 'dropdown' && column.type !== 'status')) return column;

    let settings;
    try {
      settings = JSON.parse(column.settings_str || '{}');
    } catch {
      return column;
    }

    const isAllowed = (name) => list.some((value) => same(value, name));
    const labels = Array.isArray(settings.labels)
      ? settings.labels.filter((entry) => isAllowed(entry?.name))
      : Object.fromEntries(Object.entries(settings.labels || {}).filter(([, name]) => isAllowed(name)));

    const present = Array.isArray(labels) ? labels.map((entry) => entry.name) : Object.values(labels);
    const missing = list.filter((value) => !present.some((name) => same(name, value)));
    if (missing.length) {
      log(`Board ${boardId}: "${column.title}" has no option ${missing.map((v) => `"${v}"`).join(', ')} - not offered`);
    }

    return { ...column, settings_str: JSON.stringify({ ...settings, labels }) };
  });
}
