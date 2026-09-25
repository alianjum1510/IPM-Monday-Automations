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
  let current = null;

  for (const rawLine of String(text || '').split('\n')) {
    const line = rawLine.trim();
    if (!line) continue;

    const match = line.match(KEY_LINE);
    if (match) {
      current = match[1].toUpperCase();
      fields[current] = match[2].trim();
    } else if (current) {
      fields[current] = `${fields[current]} ${line}`.trim();
    }
  }

  for (const [key, value] of Object.entries(fields)) {
    fields[key] = clean(key, value);
  }

  return fields;
}

/** Strips the model's bracket placeholders and normalises "not found" to ''. */
function clean(key, value) {
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

  const lowered = out.toLowerCase().replace(/[.]$/, '');
  if (EMPTY_VALUES.has(lowered) && !(NO_IS_A_VALUE.has(key) && lowered === 'no')) {
    return '';
  }
  if (lowered.startsWith('not found')) return '';

  if (key === 'REGISTRATION_NUMBER') return registrationOnly(out);

  return out;
}

/**
 * The model tacks commentary onto the number:
 * "KRS 0000657029 — no German HRB/HRA found after extensive search".
 * The column wants the number alone, so the value is cut at the first dash,
 * semicolon or parenthesis and the first piece that carries a digit is kept.
 * No digit anywhere means no number was found at all.
 */
function registrationOnly(value) {
  const parts = value.split(/\s+[—–-]\s+|[;(]/).map((part) => part.replace(/[\s),.]+$/, '').trim());
  return parts.find((part) => /\d/.test(part)) || '';
}
