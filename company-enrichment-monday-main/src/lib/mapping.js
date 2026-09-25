/**
 * Maps parsed research fields onto board columns.
 *
 * Columns are resolved by TITLE, not id: the two boards this block runs on
 * (5100825258 "Warm Lead Mining Board", 5100463291 "Lead Mining Board") carry
 * the same titles behind different ids, so a title lookup is what makes one
 * deployment serve both. A column that does not exist on the board is skipped.
 */
import { matchTaxonomyItem } from './taxonomy.js';

/**
 * The email now goes to "Company Email", not "Email".
 *
 * "Email" (lead_email) is the human contact's own address, captured during
 * mining; enrichment returns the company's general address, so overwriting
 * lead_email destroyed the mined value. NEVER_WRITE keeps that from coming back.
 */
export const NEVER_WRITE = new Set(['Email']);

/**
 * The stage a successfully enriched item lands on.
 *
 * Enrichment produces the data; a human still has to authenticate it. The stage
 * moves in the SAME write as the data, so a lead can never sit fully filled in
 * while still reading "Inbound".
 *
 * This is matched against the labels the column ALREADY has - never written
 * verbatim. The first attempt wrote the literal string and monday, with
 * `create_labels_if_missing`, happily made a second "Data authentication ..."
 * next to the board's own "Data Authentication ...", differing only in one
 * capital letter. Matching is case- and punctuation-insensitive and falls back
 * to the "data authentication" prefix, so the board owner can rename or
 * recapitalise the label without breaking this. If nothing matches, the stage
 * is left alone and the run says so - a wrong stage is worse than an old one.
 */
export const LIFECYCLE_STAGE_TITLE = 'Lifecycle Stage';
export const LIFECYCLE_STAGE_ENRICHED = 'Data authentication required';

/** Enough of the label to recognise it after a rename. */
const LIFECYCLE_STAGE_PREFIX = 'data authentication';

/**
 * The stages enrichment is allowed to move a lead OFF.
 *
 * The stage write used to be unconditional, and research takes minutes: a lead
 * that booked a discovery call while its enrichment was still running got
 * dragged back from "Discovery Booked" to "Data Authentication Required" when
 * the run finished. Last write wins, and enrichment was always last.
 *
 * So the stage only moves when the lead is still on a stage that comes BEFORE
 * enrichment - an empty stage, "Inbound", or the enrichment stage itself (a
 * re-run). Anything the sales flow has advanced to - Discovery Booked, Data
 * Complete, Disqualified, Nurture List, Short Route- Discovery - is left exactly
 * where it is, and the run log says the stage was held.
 *
 * An allowlist, not a blocklist of downstream stages: a new downstream label
 * added to the board must not silently become overwritable. A board whose leads
 * arrive on some other starting stage sets LIFECYCLE_STAGE_SOURCES.
 */
export const LIFECYCLE_STAGE_SOURCES = ['Inbound', LIFECYCLE_STAGE_ENRICHED];

/**
 * Whether enrichment may write the stage, given the stage the item is on NOW.
 *
 * Matched the same way as the labels themselves - case- and
 * punctuation-insensitive, with the "data authentication" prefix as the
 * fallback - so a renamed or recapitalised label does not turn the guard off.
 */
export function mayAdvanceStage(currentLabel, sources = LIFECYCLE_STAGE_SOURCES) {
  const current = normalise(currentLabel);

  // Nothing to protect: the lead has no stage at all.
  if (!current) return true;

  // Any "Data Authentication ..." variant, including the casing duplicate an
  // earlier build invented, is still a pre-enrichment stage.
  if (current.startsWith(normalise(LIFECYCLE_STAGE_PREFIX))) return true;

  return sources.some((source) => normalise(source) === current);
}

/**
 * title on the board <- field from the research output.
 *
 * `constant` writes a fixed value instead of a researched one.
 */
export const COLUMN_PLAN = [
  { title: LIFECYCLE_STAGE_TITLE, constant: LIFECYCLE_STAGE_ENRICHED, matchPrefix: LIFECYCLE_STAGE_PREFIX },
  { title: 'Company / Customer Name', field: 'CORRECT_NAME' },
  { title: 'Full Address', field: 'CORRECT_ADDRESS' },
  { title: 'Address Line 1', field: 'ADDRESS_LINE_1' },
  { title: 'Address Line 2', field: 'ADDRESS_LINE_2' },
  { title: 'Address Line 3', field: 'ADDRESS_LINE_3' },
  { title: 'Postal Code', field: 'POSTAL_CODE' },
  { title: 'City', field: 'CITY' },
  { title: 'State', field: 'STATE' },
  { title: 'District', field: 'DISTRICT' },
  { title: 'Country', field: 'COUNTRY' },
  { title: 'Country Code', field: 'COUNTRY_CODE', derive: diallingCode },
  { title: 'Registration Number', field: 'REGISTRATION_NUMBER' },
  { title: 'D&B Number', field: 'D_AND_B_NUMBER' },
  { title: 'Website', field: 'HOMEPAGE' },
  { title: 'LinkedIn Profile', field: 'LINKEDIN_PROFILE' },
  { title: 'Contact Name', field: 'CONTACT_NAME' },
  { title: 'Company Email', field: 'COMPANY_EMAIL' },
  { title: 'Main Phone', field: 'MAIN_PHONE' },
  { title: 'Mobile Number', field: 'MOBILE_NUMBER' },
  { title: 'Fax', field: 'FAX' },
  { title: 'Phone Type', field: 'PHONE_TYPE' },
  { title: 'Company Size', field: 'COMPANY_SIZE' },
  { title: 'Estimated Annual Revenue', field: 'ESTIMATED_ANNUAL_REVENUE' },
  { title: 'Company Structure', field: 'COMPANY_STRUCTURE' },
  { title: 'Ownership Type', field: 'OWNERSHIP_TYPE', fallbackField: 'CLASSIFICATION' },
  /**
   * Both are board_relation columns: the value written is a link to an item on
   * a taxonomy board, and the board's mirrors read the score through that link.
   * Left out of the plan entirely until now, which is why Industry Score, Role
   * Score, Hauptbrachen and Department were all empty and Initial Lead Score
   * scored every enriched lead on incomplete inputs.
   */
  { title: 'Industry', field: 'INDUSTRY' },
  { title: 'Job Function', field: 'JOB_FUNCTION' },
  { title: 'Comments', field: '__NOTES__' },
];

/**
 * Empty values are filled with "N/A".
 *
 * A link, email or phone column carries its own display label, so "N/A" can be
 * written into it and the cell reads N/A instead of sitting blank - that is
 * what puts N/A in LinkedIn Profile, Website and Mobile Number.
 *
 * Number, date and country columns are the exception: monday parses those into
 * a numeric or ISO value and has nowhere to keep the string "N/A". They stay
 * empty. Nothing here can break a write - change_multiple_column_values is
 * all-or-nothing, but writeColumns drops whatever monday rejects, names it in
 * the log, and retries the rest.
 */
export const NA_TEXT = 'N/A';

const NA_BY_TYPE = {
  text: () => NA_TEXT,
  long_text: () => ({ text: NA_TEXT }),
  dropdown: () => ({ labels: [NA_TEXT] }),
  link: () => ({ url: NA_TEXT, text: NA_TEXT }),
  email: () => ({ email: NA_TEXT, text: NA_TEXT }),
  phone: () => ({ phone: NA_TEXT, countryShortName: '' }),
};

const EMAIL_RE = /[^\s@]+@[^\s@]+\.[^\s@]{2,}/;

/**
 * Builds the `column_values` payload.
 *
 * Comments is composed last, whatever its position in the plan, so it can carry
 * the values no controlled column would accept.
 *
 * `relations` carries the taxonomy items for the board_relation columns, keyed
 * by column id - fetched before the write because a relation cannot be resolved
 * from the researched string alone. Absent, those columns are skipped, so this
 * stays a pure function and the mapper remains synchronously testable.
 *
 * @returns {{values: Record<string, unknown>, filled: string[], skipped: string[],
 *            unmatched: Array<{title: string, value: string}>,
 *            linked: Array<{title: string, name: string, id: string}>,
 *            ambiguous: Array<{title: string, name: string, ids: string[]}>}}
 */
export function buildColumnValues(columns, fields, relations = {}) {
  const byTitle = new Map();
  for (const column of columns) {
    if (!byTitle.has(column.title)) byTitle.set(column.title, column);
  }

  const values = {};
  const filled = [];
  const skipped = [];
  const unmatched = [];
  const linked = [];
  const ambiguous = [];

  const notesEntry = COLUMN_PLAN.find((entry) => entry.field === '__NOTES__');

  for (const entry of COLUMN_PLAN) {
    if (NEVER_WRITE.has(entry.title) || entry === notesEntry) continue;

    const column = byTitle.get(entry.title);
    if (!column) continue;

    let raw;
    if (entry.constant !== undefined) raw = entry.constant;
    else if (entry.derive) raw = entry.derive(fields, column);
    else raw = fields[entry.field] || (entry.fallbackField ? fields[entry.fallbackField] : '') || '';

    /**
     * A relation resolves against the taxonomy board's items rather than the
     * column's own settings, so it is handled here where `relations` is in
     * scope. Anything it links is reported so the run log can name it.
     */
    if (column.type === 'board_relation') {
      const match = matchTaxonomyItem(relations[column.id], raw);

      if (match) {
        values[column.id] = { item_ids: [match.id] };
        linked.push({ title: entry.title, name: match.name, id: match.id });
        if (match.ambiguous.length) {
          ambiguous.push({ title: entry.title, name: match.name, ids: match.ambiguous });
        }
        continue;
      }

      // No item to point at. A relation has no "N/A" to fall back on, so the
      // researched value is preserved in Comments and the cell stays empty.
      const researchedRelation = String(raw || '').trim();
      if (researchedRelation) unmatched.push({ title: entry.title, value: researchedRelation });
      skipped.push(entry.title);
      continue;
    }

    const formatted = formatValue(column, raw, fields, entry);

    if (formatted !== undefined) {
      values[column.id] = formatted;
      continue;
    }

    // A real value the column's own vocabulary has no room for - keep it in the
    // notes rather than dropping it or inventing an option for it.
    const researched = String(raw || '').trim();
    if (researched && (column.type === 'dropdown' || column.type === 'status')) {
      unmatched.push({ title: entry.title, value: researched });
    }

    // Nothing usable for this column - say so in the cell where monday can hold it.
    const naValue = NA_BY_TYPE[column.type];
    if (naValue) {
      values[column.id] = naValue();
      filled.push(entry.title);
    } else {
      skipped.push(entry.title);
    }
  }

  const notesColumn = notesEntry && byTitle.get(notesEntry.title);
  if (notesColumn) {
    values[notesColumn.id] = formatValue(notesColumn, composeNotes(fields, unmatched), fields, notesEntry);
  }

  return { values, filled, skipped, unmatched, linked, ambiguous };
}

/** Returns the monday-shaped value, or undefined when there is nothing to write. */
function formatValue(column, raw, fields, entry = {}) {
  const value = String(raw || '').trim();
  if (!value) return undefined;

  switch (column.type) {
    case 'text':
      return value;

    case 'long_text':
      return { text: value.slice(0, 2000) };

    /**
     * A dropdown with a defined list is a controlled vocabulary - "Country
     * Code" holds dialling codes, and writing "DE" into it created a "DE"
     * option next to +49. An unmatched value is reported, not invented; only a
     * dropdown with no labels of its own is treated as free text.
     */
    case 'dropdown': {
      const wanted = value.split(/[;,]/)[0].trim().slice(0, 80);
      if (!statusLabels(column).length) return { labels: [wanted] };

      const match = findStatusLabel(column, wanted, entry.matchPrefix);
      return match ? { labels: [match.label] } : undefined;
    }

    case 'email': {
      const match = value.match(EMAIL_RE);
      return match ? { email: match[0], text: match[0] } : undefined;
    }

    case 'phone': {
      const digits = value.replace(/[^\d+]/g, '');
      if (digits.replace(/\D/g, '').length < 6) return undefined;
      return { phone: digits, countryShortName: countryCodeOf(fields) };
    }

    case 'link': {
      const url = value.startsWith('http') ? value : `https://${value.replace(/^\/+/, '')}`;
      if (!/^https?:\/\/[^\s.]+\.[^\s]{2,}$/i.test(url)) return undefined;
      return { url, text: url.replace(/^https?:\/\//, '').replace(/\/$/, '') };
    }

    case 'country': {
      const code = countryCodeOf(fields);
      return code ? { countryCode: code, countryName: fields.COUNTRY || value } : undefined;
    }

    case 'numbers': {
      const digits = value.replace(/[^\d]/g, '');
      return digits ? String(Number(digits)) : undefined;
    }

    case 'date': {
      return /^\d{4}-\d{2}-\d{2}$/.test(value) ? { date: value } : undefined;
    }

    /**
     * By index, against a label the column already has. Writing `{label: ...}`
     * with `create_labels_if_missing` invents a near-duplicate on any casing
     * difference, which is exactly the bug this replaced.
     */
    case 'status': {
      const match = findStatusLabel(column, value, entry.matchPrefix);
      return match ? { index: match.index } : undefined;
    }

    default:
      return undefined;
  }
}

/**
 * The labels a status or dropdown column already carries.
 *
 * `settings_str` is JSON-in-a-string and the two column types disagree on its
 * shape - status is `{"labels":{"0":"Inbound"}}`, dropdown is
 * `{"labels":[{"id":1,"name":"+49"}]}`. Both normalise to {index, label}.
 */
export function statusLabels(column) {
  let settings;
  try {
    settings = JSON.parse(column.settings_str || '{}');
  } catch {
    return [];
  }

  const labels = settings.labels;
  const entries = Array.isArray(labels)
    ? labels.map((entry) => ({ index: Number(entry?.id), label: String(entry?.name ?? '') }))
    : Object.entries(labels || {}).map(([index, label]) => ({
        index: Number(index),
        label: String(label ?? ''),
      }));

  return entries
    .filter((entry) => entry.label.trim() && Number.isFinite(entry.index))
    .sort((a, b) => a.index - b.index);
}

const normalise = (value) => String(value).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

/**
 * Finds an existing label on a status column.
 *
 * Ties break to the LOWEST index: the board's own label was created before any
 * duplicate this app may have added, so the older one wins.
 *
 * @returns {{index: number, label: string}|null}
 */
export function findStatusLabel(column, wanted, prefix) {
  const labels = statusLabels(column);
  const target = normalise(wanted);

  const exact = labels.find((entry) => normalise(entry.label) === target);
  if (exact) return exact;

  if (!prefix) return null;
  const normalisedPrefix = normalise(prefix);
  return labels.find((entry) => normalise(entry.label).startsWith(normalisedPrefix)) || null;
}

/**
 * "Country Code" is a dropdown of dialling codes (+49, +1, +212 ...), not the
 * ISO code. The ISO code still goes to the `country` column, which wants it.
 *
 * The researched phone numbers are the better source - they carry the dialling
 * code directly - so they are tried first and the ISO map is the fallback for a
 * lead with no phone at all. Longest match wins, or +1 would swallow +212.
 */
const ISO_TO_DIALLING = {
  AT: '+43', BE: '+32', CH: '+41', CZ: '+420', DE: '+49', DK: '+45', ES: '+34',
  FR: '+33', GB: '+44', IE: '+353', IT: '+39', LU: '+352', NL: '+31', PL: '+48',
  PT: '+351', SE: '+46', US: '+1',
};

function diallingCode(fields, column) {
  const available = statusLabels(column)
    .map((entry) => entry.label.trim())
    .filter((label) => /^\+\d+$/.test(label))
    .sort((a, b) => b.length - a.length);

  for (const phone of [fields.MAIN_PHONE, fields.MOBILE_NUMBER, fields.FAX]) {
    const digits = String(phone || '').replace(/[^\d+]/g, '');
    if (!digits.startsWith('+')) continue;

    const match = available.find((label) => digits.startsWith(label));
    if (match) return match;
  }

  return ISO_TO_DIALLING[countryCodeOf(fields)] || '';
}

function countryCodeOf(fields) {
  const code = String(fields.COUNTRY_CODE || '').trim().toUpperCase();
  if (/^[A-Z]{2}$/.test(code)) return code;
  return /deutschland|germany/i.test(String(fields.COUNTRY || '')) ? 'DE' : '';
}

/**
 * Everything the research produced that has no column of its own - VAT number,
 * registry court, confidences, sources, company status - collected into the
 * Comments column so the verification trail is not lost.
 */
function composeNotes(fields, unmatched = []) {
  const lines = [];
  const add = (label, key) => {
    const value = fields[key];
    if (value) lines.push(`${label}: ${value}`);
    else lines.push(`${label}: ${NA_TEXT}`);
  };

  add('VAT (USt-IdNr)', 'UID_NUMBER');
  add('VAT confidence', 'VAT_CONFIDENCE');
  add('HRB confidence', 'HRB_CONFIDENCE');
  add('Registry court', 'REGISTRY_COURT');
  add('Handelsregister verified', 'HANDELSREGISTER_VERIFIED');
  add('Company status', 'COMPANY_STATUS');
  add('Classification', 'CLASSIFICATION');
  add('Overall confidence', 'CONFIDENCE');
  add('Verification source', 'VERIFICATION_SOURCE');
  add('Registry source', 'REGISTRY_SOURCE');

  // Researched, but the column's options had no home for it.
  for (const entry of unmatched) {
    lines.push(`${entry.title} (no matching option): ${entry.value}`);
  }

  if (fields.NOTES) lines.push('', fields.NOTES);

  return lines.join('\n');
}
