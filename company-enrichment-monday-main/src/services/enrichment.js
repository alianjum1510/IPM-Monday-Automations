import { env } from '../config/env.js';
import { log } from '../lib/logger.js';
import { buildPrompt } from '../lib/prompt.js';
import { parseEnrichment } from '../lib/parse.js';
import {
  buildColumnValues,
  mayAdvanceStage,
  statusLabels,
  LIFECYCLE_STAGE_ENRICHED,
  LIFECYCLE_STAGE_SOURCES,
  LIFECYCLE_STAGE_TITLE,
} from '../lib/mapping.js';
import { loadRelationTaxonomies, taxonomyChoices } from '../lib/taxonomy.js';
import { getBoard, getItem, writeColumns } from './monday.js';
import { research } from './openai.js';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Address parts, in the order they read on the board. */
const ADDRESS_PARTS = [
  'Address Line 1',
  'Address Line 2',
  'Address Line 3',
  'Postal Code',
  'City',
  'District',
  'State',
  'Country',
];

/**
 * The whole job for one item: read it, research it, write the columns back.
 * Runs detached from the HTTP response - monday only waits for the ack.
 */
export async function enrichItem(boardId, itemId) {
  const item = await getItem(itemId);

  if (!item) throw new Error(`item ${itemId} not found`);
  if (item.state && item.state !== 'active') {
    log(`Item ${itemId}: ${item.state} — skipping`);
    return { success: true, boardId: String(boardId), itemId: String(itemId), skipped: item.state };
  }

  const board = await getBoard(boardId);
  const byId = new Map(board.columns.map((column) => [column.id, column]));
  const text = {};
  for (const value of item.column_values || []) {
    const column = byId.get(value.id);
    if (column) text[column.title] = (value.text || '').trim();
  }

  const companyName = text['Company / Customer Name'] || item.name || '';
  const address = composeAddress(text);

  if (!companyName && !address) {
    log(`Item ${itemId}: no company name or address — skipping`);
    return { success: true, boardId: String(boardId), itemId: String(itemId), enriched: false };
  }

  log(`Item ${itemId}: enriching "${companyName}" / "${address}"`);

  /**
   * Industry and Job Function are board_relation columns, so their vocabulary
   * lives on other boards and has to be read BEFORE the research: the model is
   * given the exact list and asked to echo one entry back, because the taxonomy
   * is German and a free-text guess would never match. Cached per container, so
   * this is normally free.
   */
  const relations = await loadRelationTaxonomies(board.columns);
  const choices = {
    industries: taxonomyChoices(relations, board.columns, 'Industry'),
    jobFunctions: taxonomyChoices(relations, board.columns, 'Job Function'),
  };

  const { text: answer, searched, searchCount } = await research(
    buildPrompt(companyName, address, choices),
  );
  const fields = parseEnrichment(answer);

  if (!Object.keys(fields).length) {
    throw new Error(`no parsable fields in the model output for item ${itemId}`);
  }

  const { values, filled, skipped, unmatched, linked, ambiguous } = buildColumnValues(
    board.columns,
    fields,
    relations,
  );

  if (env.boardItemDelayMs) await sleep(env.boardItemDelayMs);

  // The stage read at the top of this run is minutes stale by the time the
  // research comes back, and the lead may have moved on in the meantime - that
  // is how a booked discovery call ended up back on "Data Authentication
  // Required". Re-read it as late as possible and drop the stage from the write
  // unless the lead is still on a pre-enrichment stage. The data still lands.
  const stageColumn = board.columns.find((entry) => entry.title === LIFECYCLE_STAGE_TITLE);
  const held = await holdStageIfAdvanced(stageColumn, itemId, values);

  const { written, dropped } = await writeColumns(boardId, itemId, values);

  // The stage column travels with the data; if it was held, monday rejected it,
  // or the column has no label to match, the item is still on its old stage and
  // that has to be visible in the log.
  const stage = describeStageWrite(board.columns, values, dropped, held);

  const verified = /^yes$/i.test(fields.HANDELSREGISTER_VERIFIED || '') ? 'yes' : 'no';
  const registration = fields.REGISTRATION_NUMBER || 'none';
  const confidence = fields.CONFIDENCE || 'unknown';

  log(
    `Item ${itemId}: updated ${written} columns ` +
      `(verified=${verified}, reg=${registration}, hr=${fields.HANDELSREGISTER_VERIFIED || 'No'}, ` +
      `confidence=${confidence}, lifecycle stage=${stage}) ` +
      `[N/A filled: ${filled.length}, left empty: ${skipped.length}, ` +
      `web searches: ${searched ? searchCount : 'disabled'}]` +
      // Names the option a board owner may want to add to a dropdown.
      (unmatched.length
        ? ` no matching option: ${unmatched.map((e) => `${e.title}="${e.value}"`).join(', ')}`
        : '') +
      // The relations feed Initial Lead Score, so the run says what they landed on.
      (linked.length ? ` linked: ${linked.map((e) => `${e.title}="${e.name}"`).join(', ')}` : '') +
      // Two taxonomy items share a name and they may carry different scores.
      (ambiguous.length
        ? ` ambiguous taxonomy: ${ambiguous
            .map((e) => `${e.title}="${e.name}" (${e.ids.join('/')}, took ${e.ids[0]})`)
            .join(', ')}`
        : ''),
  );

  return {
    success: true,
    boardId: String(boardId),
    itemId: String(itemId),
    enriched: true,
    verified: verified === 'yes',
    columnsWritten: written,
    naFilled: filled.length,
    linked: linked.map((entry) => entry.title),
  };
}

/**
 * Removes the stage from the write when the lead has moved on since the run
 * started, and reports the stage it was left on.
 *
 * The extra read costs one query per run - cheap next to minutes of research,
 * and it is the only thing standing between a mid-run booking and a stage that
 * silently walks backwards. monday has no compare-and-swap, so the gap between
 * this read and the write cannot be closed entirely; it goes from minutes to
 * milliseconds.
 *
 * @returns {string} the stage the write was held at, or '' if it may proceed
 */
async function holdStageIfAdvanced(column, itemId, values) {
  if (!column || values[column.id] === undefined) return '';

  const fresh = await getItem(itemId);
  const current = (fresh?.column_values || []).find((entry) => entry.id === column.id);
  const label = (current?.text || '').trim();

  const sources = env.lifecycleStageSources.length ? env.lifecycleStageSources : LIFECYCLE_STAGE_SOURCES;
  if (mayAdvanceStage(label, sources)) return '';

  delete values[column.id];
  return label;
}

/**
 * What actually happened to the Lifecycle Stage column, for the run log.
 *
 * Two of these need a human. "held" means the lead advanced while the research
 * ran, so the data landed on a lead that is already further down the funnel.
 * "no matching label" means the column carries nothing recognisable as the
 * post-enrichment stage, so the lead keeps whatever stage it had.
 */
function describeStageWrite(columns, values, dropped, held = '') {
  const column = columns.find((entry) => entry.title === LIFECYCLE_STAGE_TITLE);
  if (!column) return 'no such column on this board';

  if (held) return `held at "${held}" - the lead advanced while the research ran`;

  const value = values[column.id];
  if (!value) {
    const available = statusLabels(column).map((entry) => entry.label);
    return `no matching label for "${LIFECYCLE_STAGE_ENRICHED}" (column has: ${available.join(' | ') || 'none'})`;
  }

  if (dropped.includes(column.id)) return 'REJECTED by monday - stage unchanged';

  const written = statusLabels(column).find((entry) => entry.index === value.index);
  return `"${written?.label ?? value.index}"`;
}

/**
 * Prefers the structured parts, because "Address" alone is often just a street.
 * Falls back to whatever single address column the board has.
 */
function composeAddress(text) {
  const parts = ADDRESS_PARTS.map((title) => text[title]).filter(Boolean);
  if (parts.length) return parts.join(', ');
  return text['Full Address'] || text.Address || '';
}
