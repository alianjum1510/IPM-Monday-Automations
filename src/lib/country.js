/**
 * Classifies the lead's country from what the user entered, BEFORE the research.
 *
 * The research is then scoped to that one country, so a same-named company
 * abroad cannot be found instead. The cheap, certain signals are tried here in
 * code; only an address none of them can place goes to the model
 * (`classifyCountry` in services/openai.js), which reads the city, postal code
 * format and region.
 *
 * Country names come from Intl rather than a hand-kept list, in the languages
 * an address on these boards is written in - so "Deutschland", "Österreich",
 * "Schweiz", "Nederland" and "Germany" are all recognised for every country.
 */

const LANGUAGES = ['en', 'de', 'fr', 'it', 'es', 'nl', 'pl', 'pt', 'cs', 'da', 'sv'];

/**
 * Region codes that are not countries - and historical ones Intl still names,
 * or "Deutschland" would classify as DD, East Germany.
 */
const NOT_COUNTRIES = new Set([
  'AC', 'CP', 'DG', 'EA', 'EU', 'EZ', 'IC', 'QO', 'TA', 'UN', 'XA', 'XB', 'ZZ',
  'AN', 'BU', 'CS', 'DD', 'FX', 'NT', 'SU', 'TP', 'YU', 'ZR',
]);

const englishName = new Intl.DisplayNames(['en'], { type: 'region' });

const fold = (value) =>
  String(value || '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();

/** Folded country name, in any of LANGUAGES -> ISO code. */
const BY_NAME = (() => {
  const byName = new Map();
  const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const displays = LANGUAGES.map((language) => new Intl.DisplayNames([language], { type: 'region' }));

  for (const a of letters) {
    for (const b of letters) {
      const code = a + b;
      if (NOT_COUNTRIES.has(code)) continue;
      for (const display of displays) {
        const name = display.of(code);
        if (name && name !== code && !byName.has(fold(name))) byName.set(fold(name), code);
      }
    }
  }

  // Everyday forms Intl does not use.
  for (const [name, code] of [['usa', 'US'], ['uk', 'GB'], ['england', 'GB'], ['holland', 'NL'], ['brd', 'DE']]) {
    byName.set(name, code);
  }
  return byName;
})();

/** "D-71336", "A-1010", "CH-8000" - the old European vehicle-code postal prefix. */
const POSTAL_PREFIX = {
  D: 'DE', A: 'AT', CH: 'CH', F: 'FR', I: 'IT', NL: 'NL', B: 'BE', L: 'LU',
  PL: 'PL', CZ: 'CZ', DK: 'DK', S: 'SE', E: 'ES', P: 'PT', FL: 'LI', H: 'HU',
};
const POSTAL_PREFIX_RE = /(?<![\p{L}\d])(CH|NL|PL|CZ|DK|FL|D|A|F|I|B|L|S|E|P|H)\s?-\s?\d{4,5}(?!\d)/u;

export function countryName(code) {
  return /^[A-Z]{2}$/.test(code || '') ? englishName.of(code) : '';
}

/** A country name or ISO code as a whole value: "Germany", "Deutschland", "DE". */
export function countryCode(value) {
  const folded = fold(value);
  if (!folded) return '';
  if (BY_NAME.has(folded)) return BY_NAME.get(folded);

  const code = String(value).trim().toUpperCase();
  return /^[A-Z]{2}$/.test(code) && !NOT_COUNTRIES.has(code) && countryName(code) !== code ? code : '';
}

/**
 * The country the user's input names, or null when it names none.
 *
 * An address is only read at the places a country actually sits - a whole
 * comma segment, or the words the address ends on - so "Schweizer Straße" or
 * "Georgia Allee" in the street cannot classify a lead.
 *
 * @returns {{code: string, name: string, source: string}|null}
 */
export function countryFromInput(countryColumn, address) {
  const found = (code, source) => ({ code, name: countryName(code), source });

  const fromColumn = countryCode(countryColumn);
  if (fromColumn) return found(fromColumn, 'Country column');

  const segments = String(address || '').split(',').map((segment) => segment.trim()).filter(Boolean);
  for (const segment of [...segments].reverse()) {
    const words = segment.replace(/\d+/g, ' ').trim().split(/\s+/);
    // The segment itself, then its last one to three words ("1010 Wien Österreich").
    for (const take of [words.length, 3, 2, 1]) {
      if (take > words.length) continue;
      const code = BY_NAME.get(fold(words.slice(-take).join(' ')));
      if (code) return found(code, 'country name in address');
    }
  }

  const prefix = String(address || '').match(POSTAL_PREFIX_RE);
  if (prefix) return found(POSTAL_PREFIX[prefix[1]], 'postal prefix in address');

  return null;
}
