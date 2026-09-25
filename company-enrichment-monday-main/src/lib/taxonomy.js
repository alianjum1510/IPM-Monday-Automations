/**
 * The connected-board taxonomies behind the `Industry` and `Job Function`
 * columns.
 *
 * Both are `board_relation` columns, not text or dropdown: the cell holds a
 * LINK to an item on a separate taxonomy board, and that link is what the
 * board's mirrors (Hauptbrachen, Industry Score, Department, Role Score) read
 * through to reach `Initial Lead Score`. A string cannot be written into one -
 * the payload is `{"item_ids": [<id>]}` - which is why enrichment left both
 * blank and the lead score ran on incomplete inputs.
 *
 * Both lead boards point at the SAME two taxonomy boards, so the cache is
 * shared across them:
 *
 *   Industry      -> 5094116229  "Subitems of Sandbox Hauptbranchen & ..."  52 items
 *   Job Function  -> 5095332326  "Sandbox Abteilung & Funktion"            197 items
 *
 * Nothing here ever creates a taxonomy item. The names carry the scoring
 * weights, so an invented one would be a scoring error that looks like data -
 * the same mistake `create_labels_if_missing` made with the duplicate
 * "Data authentication required" label. An unmatched value goes to Comments.
 */
import { getBoardItems } from '../services/monday.js';
import { log } from '../lib/logger.js';

/** The relation columns enrichment fills, by title. */
export const RELATION_TITLES = ['Industry', 'Job Function'];

/**
 * The board a relation column points at.
 *
 * `boardIds` is the field to trust: the cold board's Industry column
 * (board_relation_mm5b6cag) carries `{"boardIds":[5094116229]}` with no
 * `boardId` key at all, so reading `boardId` alone finds nothing on that board
 * and only the warm board would ever be filled.
 */
export function connectedBoardId(column) {
  let settings;
  try {
    settings = JSON.parse(column?.settings_str || '{}');
  } catch {
    return '';
  }

  const first = Array.isArray(settings.boardIds) ? settings.boardIds[0] : null;
  return String(first ?? settings.boardId ?? '') || '';
}

/**
 * Folded hard enough to survive how a model retypes German.
 *
 * Umlauts are transliterated rather than stripped, so "Geschäftsführung" and
 * "geschaeftsfuehrung" land on the same key instead of on "geschftsfhrung" and
 * a miss. "&" becomes "und" because the taxonomy is full of "Handel & Vertrieb"
 * and a model that types the word out should still match.
 */
const normalise = (value) =>
  String(value)
    .toLowerCase()
    .replace(/ä/g, 'ae')
    .replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue')
    .replace(/ß/g, 'ss')
    .replace(/&/g, ' und ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();

/** The part before the first bracket or semicolon: "Großhandel (Industrie-; ...)" -> "Großhandel". */
const head = (value) => String(value).split(/[(;,\/]/)[0].trim();

/**
 * Finds the taxonomy item a researched value refers to.
 *
 * The model is handed the exact list and asked to echo one name back, so layer
 * 1 carries almost every case; the rest is the safety net for a model that
 * paraphrases or adds its own bracket.
 *
 * Ties break to the LOWEST item id - the oldest item wins, the same rule
 * findStatusLabel uses for duplicate labels. This is not cosmetic: "Geschäfts-
 * führer" exists twice on the Job Function board with Role Score 13 and 10, so
 * an unstable tie-break would make the lead score depend on API row order.
 *
 * @returns {{id: string, name: string, ambiguous: string[]}|null}
 */
export function matchTaxonomyItem(items, wanted) {
  const value = String(wanted || '').trim();
  if (!value || !items?.length) return null;

  const oldestFirst = [...items].sort((a, b) => Number(a.id) - Number(b.id));
  const target = normalise(value);
  const targetHead = normalise(head(value));

  const pick = (matches) => {
    if (!matches.length) return null;
    const [first] = matches;
    const ambiguous = matches.length > 1 ? matches.map((entry) => entry.id) : [];
    return { id: first.id, name: first.name, ambiguous };
  };

  // 1. The name exactly as the board spells it.
  const exact = oldestFirst.filter((entry) => normalise(entry.name) === target);
  if (exact.length) return pick(exact);

  // 2. Both sides reduced to their leading segment, so "Großhandel" reaches
  //    "Großhandel (Industrie-; Arbeitsschutz-; ...)".
  const byHead = oldestFirst.filter((entry) => normalise(head(entry.name)) === targetHead);
  if (byHead.length) return pick(byHead);

  /**
   * 3. One is a PREFIX of the other - the model truncated the name, or added to
   *    it. Deliberately not free substring containment: "Handel" appears inside
   *    Großhandel, Einzelhandel and Onlinehandel, and quietly picking one of
   *    those writes a score nobody chose. A wrong link is worse than no link,
   *    because no link is logged and preserved in Comments.
   *
   *    The prefix must end on a WORD boundary, or "Auto" reaches
   *    "Automobilindustrie (inkl. KFZ-Werkstätten; ...)" and four characters
   *    decide an Industry Score. "Großhandel" still reaches "Großhandel
   *    (Industrie-; ...)" because a space follows it.
   *
   *    Shortest name first, so a bare "Handel" prefers the broad category over
   *    an arbitrary specialisation, and every collision is reported as
   *    ambiguous.
   */
  const prefixes = (a, b) => a === b || a.startsWith(`${b} `);
  const byPrefix = oldestFirst
    .filter((entry) => {
      const name = normalise(entry.name);
      return prefixes(name, target) || prefixes(target, name);
    })
    .sort((a, b) => a.name.length - b.name.length || Number(a.id) - Number(b.id));

  return pick(byPrefix);
}

/**
 * boardId -> items, for the life of the container.
 *
 * A taxonomy board is a slowly-changing dimension and every run would otherwise
 * spend two extra paginated reads on it, against the same complexity budget
 * BOARD_ITEM_DELAY_MS exists to protect. A TTL keeps a newly added industry
 * from needing a redeploy to become matchable.
 */
const cache = new Map();
const TTL_MS = Number(process.env.TAXONOMY_TTL_MS) || 10 * 60 * 1000;

export async function loadTaxonomy(boardId) {
  const key = String(boardId);
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.items;

  const items = await getBoardItems(key);
  cache.set(key, { items, at: Date.now() });
  return items;
}

export function clearTaxonomyCache() {
  cache.clear();
}

/**
 * Loads the taxonomy for every relation column enrichment fills.
 *
 * A board missing one of the columns, or a column pointing nowhere, simply has
 * no entry - the mapper then treats it as "no taxonomy" and skips the column,
 * exactly as it does for a column the board does not have.
 *
 * @returns {Promise<Record<string, Array<{id: string, name: string}>>>} by column id
 */
export async function loadRelationTaxonomies(columns) {
  const byColumnId = {};

  for (const title of RELATION_TITLES) {
    const column = columns.find((entry) => entry.title === title && entry.type === 'board_relation');
    if (!column) continue;

    const boardId = connectedBoardId(column);
    if (!boardId) {
      log(`Column "${title}" (${column.id}) has no connected board - skipping`);
      continue;
    }

    try {
      const items = await loadTaxonomy(boardId);
      if (items.length) byColumnId[column.id] = items;
      else log(`Taxonomy board ${boardId} for "${title}" returned no items`);
    } catch (error) {
      // A taxonomy that cannot be read costs those two columns, not the run.
      log(`Could not load taxonomy board ${boardId} for "${title}": ${error.message}`);
    }
  }

  return byColumnId;
}

/** The list handed to the model, one name per line. */
export function taxonomyChoices(byColumnId, columns, title) {
  const column = columns.find((entry) => entry.title === title && entry.type === 'board_relation');
  const items = column ? byColumnId[column.id] : null;
  if (!items?.length) return [];

  // De-duplicated: the Job Function board spells "Geschäftsführer" twice and
  // the model does not need to see the collision.
  return [...new Set(items.map((entry) => entry.name.trim()).filter(Boolean))];
}
