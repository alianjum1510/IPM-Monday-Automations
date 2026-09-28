/**
 * Turns the model's `KEY: value` block into a plain object.
 *
 * The model is asked for one field per line, but it does wrap long NOTES over
 * several lines, so a line without a recognised KEY is appended to the field
 * that came before it.
 */

const KEY_LINE = /^\s*\*{0,2}([A-Z][A-Z0-9_&]{2,})\*{0,2}\s*:\s*(.*)$/;

/** Values the model uses to say "nothing found" - all normalise to empty. */
const EMPTY_VALUES = new Set([
  '',
  'n/a',
  'na',
  'none',
  'null',
  'unknown',
  'not found',
  'not available',
  'not applicable',
  'not found after extensive search',
  'no',
]);

/** `NOT_FOUND_KEEPS_NO` fields where a literal "No" is a real answer. */
const NO_IS_A_VALUE = new Set(['HANDELSREGISTER_VERIFIED']);

/**
 * Fields where a trailing "(handelsregister.de)" is the point, not noise.
 *
 * The prompt asks these to name their source, and Comments is where that
 * verification trail lives. Everywhere else a source citation is contamination:
 * "Contact Name" is a name, not a name plus where it was found.
 */
const KEEP_CITATIONS = new Set([
  'VAT_CONFIDENCE',
  'HRB_CONFIDENCE',
  'COMPANY_STATUS',
  'CONFIDENCE',
  'VERIFICATION_SOURCE',
  'REGISTRY_SOURCE',
  'NOTES',
]);

/**
 * Fields that hold the value and nothing else.
 *
 * The model likes to annotate the name and address it settled on -
 * "Muster GmbH (verified on handelsregister.de)", "Badstraße 1, 12345 Berlin -
 * Hauptsitz; formerly Hauptstraße 3", or a sentence on the next line. Those
 * cells are what a human reads and what gets mailed to, so the annotation is
 * cut off and moved to Comments rather than written into the cell.
 */
const NAME_FIELD = 'CORRECT_NAME';
const ADDRESS_FIELDS = new Set([
  'CORRECT_ADDRESS',
  'ADDRESS_LINE_1',
  'ADDRESS_LINE_2',
  'ADDRESS_LINE_3',
  'POSTAL_CODE',
  'CITY',
  'STATE',
  'DISTRICT',
  'COUNTRY',
]);
export const isValueOnly = (key) => key === NAME_FIELD || ADDRESS_FIELDS.has(key);

/**
 * Where the cut-off remarks travel, as `[{key, text}]`. KEY_LINE only accepts a
 * key starting with a letter, so the model cannot write to it.
 */
export const REMOVED_REMARKS = '__REMOVED_REMARKS__';

/** A whole word, umlauts included - `\b` is ASCII-only and misses "früher". */
const words = (list) => new RegExp(`(?<![\\p{L}\\d])(?:${list})(?![\\p{L}\\d])`, 'iu');

/** Words that only appear when the model is talking ABOUT the value. */
const REMARK = words(
  [
    'verif\\w*', 'confirm\\w*', 'unverified', 'unconfirmed', 'sources?', 'according', 'laut', 'gem(?:ä|ae)ß',
    'per', 'formerly', 'former', 'previously', 'früher', 'frueher', 'ehemals', 'vormals', 'now', 'aka',
    'also known', 'note[sd]?', 'hinweis', 'see also', 'siehe', 'found', 'listed', 'registered', 'registry',
    'handelsregister', 'unternehmensregister', 'impressum', 'northdata', 'creditsafe', 'companyhouse',
    'linkedin', 'website', 'homepage', 'google', 'as of', 'likely', 'probably', 'possibly', 'may', 'might',
    'unclear', 'uncertain', 'alternative\\w*', 'or', 'headquarters?', 'hq', '(?:haupt|firmen|gesellschafts)?sitz',
    'branch', 'niederlassung', 'filiale', '(?:registered|head|main) office', 'moved', 'relocated', 'umgezogen',
    'renamed', 'umfirmiert', 'changed', 'since', 'seit', 'parent', 'subsidiary', 'tochter\\w*', 'mutter\\w*',
    'based on', 'search\\w*', 'match\\w*', 'input', 'provided', 'original', 'typo', 'correct(?:ed|ion)?',
    'spelling', 'incorrect', 'differs?', 'confidence',
  ].join('|'),
);

/**
 * English prose. German addresses never contain these words, so a segment that
 * does is a sentence about the address. Not applied to the name on its own:
 * "The Coca-Cola Company GmbH" is a name.
 */
const PROSE = words('the|is|was|were|are|has|have|had|which|this|that|its|but|not|company|appears?|seems?');

const LEGAL_FORMS = 'gmbh|mbh|ag|kg|kgaa|ohg|gbr|ug|se|mbb|e\\.\\s?k\\.?|e\\.\\s?v\\.?|eg|ltd\\.?|inc\\.?|llc|plc';

/** The name so far ends on its legal form, so whatever follows is not the name. */
const ENDS_ON_LEGAL_FORM = new RegExp(`(?<![\\p{L}\\d])(?:${LEGAL_FORMS})(?:\\s*\\))?\\s*$`, 'iu');

/** Greedy, so it finds the LAST legal form: "GmbH & Co. KG verified" keeps "& Co. KG". */
const AFTER_LAST_LEGAL_FORM = new RegExp(`^(.*(?<![\\p{L}\\d])(?:${LEGAL_FORMS})(?![\\p{L}\\d])\\.?)\\s+(.+)$`, 'iu');

/** The placeholder label echoed in front of the value: "Legal name: Muster GmbH". */
const LABEL_PREFIX = /^(?:legal|company|full|registered|verified)?\s*(?:name|address)\s*:\s*/i;

/** Dash, pipe or semicolon - and a spaced hyphen, unless it is a house-number range "1 - 3". */
const SEPARATOR = /\s+[—–|]\s+|\s*;\s*|\s+-\s+(?=\D)/g;

/** A comma, or a full stop that starts a new sentence. */
const SEGMENT = /,\s*|\.\s+(?=\p{Lu})/gu;

/** Longest plausible value; anything longer is carrying something else. */
const MAX_LENGTH = { CORRECT_NAME: 120, CORRECT_ADDRESS: 200 };
const MAX_PART_LENGTH = 100;

/** `[text](url)` - web_search cites its sources as markdown links. */
const MARKDOWN_LINK = /\[([^\]]*)\]\(\s*<?(https?:\/\/[^)\s>]+)>?\s*\)/gi;

/** A parenthesised bare domain or URL: "(svg-sued.de)", "(https://x.de/impressum)". */
const CITATION_PAREN = /\s*\((?:https?:\/\/)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:\/[^)]*)?\)/gi;

/** web_search stamps its own attribution onto every URL it hands back. */
function stripTracking(value) {
  return value
    .replace(/([?&])utm_source=openai&/gi, '$1')
    .replace(/[?&]utm_source=openai\b/gi, '');
}

export function parseEnrichment(text) {
  const fields = {};
  const remarks = [];
  let current = null;

  for (const rawLine of String(text || '').split('\n')) {
    const line = rawLine.trim();
    if (!line) continue;

    const match = line.match(KEY_LINE);
    if (match) {
      current = match[1].toUpperCase();
      fields[current] = match[2].trim();
    } else if (current && isValueOnly(current)) {
      // A second line under the name or address is a remark about it, not
      // more of it - the model is asked for one field per line.
      remarks.push({ key: current, text: line });
    } else if (current) {
      fields[current] = `${fields[current]} ${line}`.trim();
    }
  }

  for (const [key, value] of Object.entries(fields)) {
    fields[key] = clean(key, value, remarks);
  }

  if (remarks.length) fields[REMOVED_REMARKS] = remarks;

  return fields;
}

/** Strips the model's bracket placeholders and normalises "not found" to ''. */
function clean(key, value, remarks = []) {
  let out = String(value).trim();

  // Citations first: an unwrapped "[legal name](url)" would defeat the
  // placeholder check below.
  out = stripTracking(out).replace(MARKDOWN_LINK, '$1').trim();
  if (!KEEP_CITATIONS.has(key)) out = out.replace(CITATION_PAREN, '').trim();

  // "[legal name]" - an unfilled placeholder, not an answer.
  if (/^\[.*\]$/.test(out)) {
    const inner = out.slice(1, -1).trim();
    out = /^(or\b|e\.g\.|legal name|full address|court|URL|status)/i.test(inner) ? '' : inner;
  }

  out = out.replace(/^\*+|\*+$/g, '').trim();

  // Before the "not found" checks: "Not found — KRS 0000657029" still carries
  // a number, and the generic check below would throw it away.
  if (key === 'REGISTRATION_NUMBER') return registrationOnly(out);

  // "Not found" is an answer, not a remark to move to Comments.
  const nothing = out.toLowerCase().replace(/[.]$/, '');
  if (isValueOnly(key) && !EMPTY_VALUES.has(nothing) && !nothing.startsWith('not found')) {
    const { value: bare, removed } = valueOnly(key, out);
    for (const text of removed) remarks.push({ key, text });
    out = bare;
  }

  const lowered = out.toLowerCase().replace(/[.]$/, '');
  if (EMPTY_VALUES.has(lowered) && !(NO_IS_A_VALUE.has(key) && lowered === 'no')) {
    return '';
  }
  if (lowered.startsWith('not found')) return '';

  return out;
}

/**
 * Cuts the name or an address part down to the value itself.
 *
 * In order: an echoed label, bracketed remarks, a tail after a dash or
 * semicolon, and a comma segment or sentence that talks about the value. Then a
 * last check: if what is left still carries a URL, an email, a question or more
 * text than the field ever needs, it is not trusted at all - the cell is left
 * for N/A and the whole answer goes to Comments. An empty cell is recoverable,
 * a name with a note glued to it gets mailed.
 *
 * The name is handled more gently than the address. "Muster (Deutschland) GmbH"
 * and "Rhein - Main Bau GmbH" are real names, so a bracket or dash is only cut
 * from the name when it reads as a remark or follows the legal form.
 *
 * @returns {{value: string, removed: string[]}}
 */
function valueOnly(key, value) {
  const isName = key === NAME_FIELD;
  const removed = [];
  let out = value.replace(LABEL_PREFIX, '');

  // "(verified on handelsregister.de)", "[Hauptsitz]".
  out = out.replace(/\s*[([]([^()[\]]*)[)\]]/g, (whole, inner, offset, source) => {
    const keep = isName && !REMARK.test(inner) && !ENDS_ON_LEGAL_FORM.test(source.slice(0, offset));
    if (keep) return whole;
    if (inner.trim()) removed.push(inner.trim());
    return '';
  });

  // "Badstraße 115 — Hauptsitz", "Muster GmbH; formerly Alt GmbH".
  for (const match of out.matchAll(SEPARATOR)) {
    const head = out.slice(0, match.index).trim();
    const tail = out.slice(match.index + match[0].length).trim();
    if (!head || !tail) continue;

    const remark = REMARK.test(tail) || PROSE.test(tail);
    const hard = match[0].trim() !== '-';
    if (isName ? remark || ENDS_ON_LEGAL_FORM.test(head) : hard || remark) {
      removed.push(tail);
      out = head;
      break;
    }
  }

  // "Muster GmbH verified via Impressum" - words after the legal form.
  if (isName) {
    const after = out.match(AFTER_LAST_LEGAL_FORM);
    if (after && (REMARK.test(after[2]) || PROSE.test(after[2]))) {
      removed.push(after[2].trim());
      out = after[1];
    }
  }

  // "Badstraße 115, 71336 Waiblingen, as listed on the Impressum" and
  // "... Waiblingen. The company moved in 2021." The first segment is the
  // value itself and is never cut here - the final check handles that case.
  const talksAbout = (segment) => REMARK.test(segment) || (!isName && PROSE.test(segment));
  for (const match of out.matchAll(SEGMENT)) {
    const start = match.index + match[0].length;
    const next = out.slice(start).search(SEGMENT);
    const segment = out.slice(start, next === -1 ? undefined : start + next);
    if (talksAbout(segment)) {
      removed.push(out.slice(start).trim());
      out = out.slice(0, match.index);
      break;
    }
  }

  out = out.replace(/^[\s,;:|—–-]+|[\s,;:|—–-]+$/g, '').replace(/\s{2,}/g, ' ');

  const limit = MAX_LENGTH[key] || MAX_PART_LENGTH;
  const untrusted =
    /https?:\/\/|www\.|@|\?/.test(out) ||
    out.length > limit ||
    (!isName && (REMARK.test(out) || PROSE.test(out)));

  if (untrusted) return { value: '', removed: [value] };

  return { value: out, removed };
}

/** A register prefix and its number: "HRB 12345 B", "KRS 0000657029", "FN 123456a". */
const REGISTER_NUMBER = /\b[A-Z]{2,4}[.:]?\s?\d(?:[\d\s./-]*\d)?(?:\s?[A-Za-z]\b)?/;

/** The model's ways of saying it found nothing. */
const NOTHING_FOUND = /\bnot found\b|\bno\b.*\bfound\b|^(n\/?a|none|null|unknown|not available|not applicable)\b/i;

/**
 * The model tacks commentary onto the number, before or after it:
 * "KRS 0000657029 — no German HRB/HRA found after extensive search",
 * "Not found — KRS 0000657029 (Polish register)".
 * The column wants the number alone. A register prefix with a number wins
 * wherever it sits; failing that, a "nothing found" statement is empty (its
 * digits are search counts, not a number), and anything else is cut at the
 * first dash, semicolon or parenthesis.
 */
function registrationOnly(value) {
  const prefixed = value.match(REGISTER_NUMBER);
  if (prefixed) return prefixed[0].trim();

  if (NOTHING_FOUND.test(value)) return '';

  const parts = value.split(/\s+[—–-]\s+|[;(]/).map((part) => part.replace(/[\s),.]+$/, '').trim());
  return parts.find((part) => /\d/.test(part)) || '';
}
