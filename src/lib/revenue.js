/**
 * Places a researched revenue figure into one of the board's revenue bands.
 *
 * Text matching alone (findStatusLabel) only accepts an answer that already
 * spells a band - "€30 million" never matches "15M-30M EUR". So the research
 * also returns the raw figure, and this module does the arithmetic:
 *
 *   1. the bands are read from the column's CURRENT options, not a list in the
 *      code - "< 1M EUR" is [0, 1M), "1M-10M EUR" is [1M, 10M), "500M+ EUR" is
 *      [500M, infinity) - so renaming or re-cutting the bands needs no deploy;
 *   2. the figure is converted into the bands' currency (EUR -> USD when the
 *      board's options are in dollars) with the day's ECB rates;
 *   3. the band whose range contains it wins.
 *
 * Every band includes its lower bound and excludes its upper one, so a figure
 * on an edge has exactly one home: 30M goes to "30M-50M", not "15M-30M". The
 * board's own labels already read that way - "< 1M" leaves 1M out and "500M+"
 * takes 500M in.
 *
 * Pure: the exchange rates are passed in (services/fx.js fetches them), so
 * this is testable without a network.
 */

/** Multipliers, longest spelling first so "mio" is not read as "m". */
const MULTIPLIERS = [
  [/^(?:milliarden?|mrd\.?|billions?|bn|b)$/i, 1e9],
  [/^(?:millionen|millions?|mio\.?|mn|m)$/i, 1e6],
  [/^(?:tausend|thousand|tsd\.?|k|t)$/i, 1e3],
];

/**
 * A number with an optional multiplier after it. "T" only counts in front of a
 * currency - "30.000 TEUR" / "30.000 T€" is how German accounts write thousands.
 */
const AMOUNT =
  /(\d+(?:[.,\s]\d{3})*(?:[.,]\d+)?)\s*(?:(milliarden?|mrd\.?|billions?|bn|millionen|millions?|mio\.?|mn|tausend|thousand|tsd\.?|[bmk])(?![a-z])|(t)(?=\s*(?:€|eur)))?/gi;

/** Joins two amounts into a range: "1M-10M", "1 to 10 Mio.", "1 bis 10". */
const RANGE_JOIN = /^\s*(?:-|–|—|to|bis)\s*[^\d]{0,6}$/i;

/** Words that make a single amount an open-ended band. */
const BELOW = /(?:^|\s)(?:<|≤|under|below|less than|up to|bis|unter|weniger als)\s*[^\d]{0,4}$/i;
const ABOVE = /(?:^|[^a-zäöü])(?:[>≥]|(?:over|above|more than|über|ueber|ab|from)\s)[^\d]*$/i;
const PLUS_AFTER = /^\s*[a-z€$£.\s]*\+/i;

/**
 * ISO codes first, then symbols, then words. Codes are whole words so "Nokia"
 * is not kroner - except EUR, which German accounts prefix with T ("TEUR").
 */
const isoCode = (iso) => new RegExp(`(?<![a-z])${iso}(?![a-z])`, 'i');
const CURRENCIES = [
  [/(?<![a-z])USD(?![a-z])|US\$/i, 'USD'],
  [/(?<![a-su-z])EUR/i, 'EUR'],
  ...['GBP', 'CHF', 'PLN', 'CZK', 'SEK', 'NOK', 'DKK', 'HUF'].map((iso) => [isoCode(iso), iso]),
  [/€|euros?\b/i, 'EUR'],
  [/\$|dollars?\b/i, 'USD'],
  [/£|pounds?\b/i, 'GBP'],
  [/franken|francs?\b|\bFr\./i, 'CHF'],
  [/zł|zloty|złoty/i, 'PLN'],
];

export function detectCurrency(text) {
  for (const [pattern, code] of CURRENCIES) {
    if (pattern.test(String(text || ''))) return code;
  }
  return '';
}

/**
 * "30.000.000", "30,000,000", "1,2", "1.5", "30 000 000" -> a number.
 *
 * A single separator followed by exactly three digits is a thousands separator
 * ("30.000" is thirty thousand in German); anything else is a decimal point.
 */
export function parseNumber(raw) {
  const text = String(raw).replace(/\s/g, '');
  const commas = (text.match(/,/g) || []).length;
  const dots = (text.match(/\./g) || []).length;

  if (commas && dots) {
    const decimal = text.lastIndexOf(',') > text.lastIndexOf('.') ? ',' : '.';
    const thousands = decimal === ',' ? '.' : ',';
    return Number(text.split(thousands).join('').replace(decimal, '.'));
  }

  if (!commas && !dots) return Number(text);

  const separator = commas ? ',' : '.';
  const parts = text.split(separator);
  if (parts.length > 2 || parts[1].length === 3) return Number(parts.join(''));
  return Number(parts.join('.'));
}

function multiplierOf(suffix) {
  if (!suffix) return 0;
  const found = MULTIPLIERS.find(([pattern]) => pattern.test(suffix));
  return found ? found[1] : 0;
}

/** Every amount in a piece of text, with where it sits and whether it had a multiplier. */
function amounts(text) {
  const found = [];
  for (const match of String(text).matchAll(AMOUNT)) {
    const value = parseNumber(match[1]);
    if (!Number.isFinite(value)) continue;
    found.push({
      value,
      multiplier: multiplierOf(match[2] || match[3]),
      start: match.index,
      end: match.index + match[0].length,
    });
  }
  return found;
}

/** "1-10M": the first number takes the multiplier the second one carries. */
function scaled(first, second) {
  const multiplier = first.multiplier || second?.multiplier || 1;
  return first.value * multiplier;
}

/**
 * A revenue band label -> {min, max, currency}, or null when the label is not
 * a numeric band at all ("N/A", "Unknown").
 */
export function parseBand(label) {
  const text = String(label || '');
  const found = amounts(text);
  const currency = detectCurrency(text);

  if (found.length === 2 && RANGE_JOIN.test(text.slice(found[0].end, found[1].start))) {
    const min = scaled(found[0], found[1]);
    const max = scaled(found[1]);
    return max > min ? { min, max, currency } : null;
  }

  if (found.length === 1) {
    const amount = scaled(found[0]);
    const before = text.slice(0, found[0].start);
    const after = text.slice(found[0].end);

    if (BELOW.test(before)) return { min: 0, max: amount, currency };
    if (PLUS_AFTER.test(after) || ABOVE.test(before)) return { min: amount, max: Infinity, currency };
  }

  return null;
}

/**
 * The researched figure -> {amount, currency}, or null.
 *
 * Brackets are dropped first, so "(2024)" is not read as two thousand euros. A
 * range ("30-35 Mio. EUR") is placed by its midpoint. A bare number under ten
 * thousand with no multiplier is skipped: "Umsatz 2023: 30 Mio. EUR" carries a
 * year before the amount, and a lone "30" is a missing "million", not thirty
 * euros.
 */
export function parseFigure(text) {
  const plain = String(text || '').replace(/\([^)]*\)/g, ' ');
  const found = amounts(plain);

  for (let i = 0; i < found.length; i += 1) {
    const next = found[i + 1];
    const isRange = next && RANGE_JOIN.test(plain.slice(found[i].end, next.start));

    const amount = isRange
      ? (scaled(found[i], next) + scaled(next)) / 2
      : scaled(found[i]);
    const hasMultiplier = found[i].multiplier || (isRange && next.multiplier);

    if (hasMultiplier || amount >= 10000) return { amount, currency: detectCurrency(plain) };
  }

  return null;
}

/**
 * Converts between currencies with rates quoted per 1 EUR ({EUR: 1, USD: 1.08}).
 * The same currency, or a side whose currency is unknown, passes through
 * unchanged; a currency with no rate returns null rather than a guess.
 */
export function convert(amount, from, to, rates) {
  if (!from || !to || from === to) return amount;
  const fromRate = from === 'EUR' ? 1 : rates?.[from];
  const toRate = to === 'EUR' ? 1 : rates?.[to];
  if (!fromRate || !toRate) return null;
  return (amount / fromRate) * toRate;
}

/**
 * The band a figure falls into.
 *
 * @param {Array<{index: number, label: string}>} labels the column's options
 * The bands' currency is the first one any option names; options that name
 * none share it. A figure with no currency of its own is taken to be in the
 * board's currency already.
 *
 * @returns {{index: number, label: string, amount: number, currency: string,
 *            from: string, original: number}
 *          | {reason: string} | null} null when there is no figure to place
 */
export function bandForFigure(labels, figureText, rates) {
  const figure = parseFigure(figureText);
  if (!figure) return null;

  const bands = labels
    .map((option) => ({ ...option, band: parseBand(option.label) }))
    .filter((option) => option.band);

  // One parsable band is a label that happens to hold a number, not a scale.
  if (bands.length < 2) return { reason: 'the column options are not numeric bands' };

  const currency = bands.find((option) => option.band.currency)?.band.currency || '';
  const from = figure.currency || currency;

  const amount = convert(figure.amount, from, currency, rates);
  if (amount === null) return { reason: `no exchange rate for ${from} -> ${currency}` };

  const hit = bands.find((option) => option.band.min <= amount && amount < option.band.max);
  if (!hit) return { reason: `no band covers ${formatAmount(amount, currency)}` };

  return { index: hit.index, label: hit.label, amount, currency, from, original: figure.amount };
}

/** 32400000 -> "32.4M USD", for Comments and the run log. */
export function formatAmount(amount, currency = '') {
  const [divisor, suffix] =
    amount >= 1e9 ? [1e9, 'B'] : amount >= 1e6 ? [1e6, 'M'] : amount >= 1e3 ? [1e3, 'K'] : [1, ''];
  const value = Number((amount / divisor).toFixed(2));
  return `${value}${suffix}${currency ? ` ${currency}` : ''}`;
}
