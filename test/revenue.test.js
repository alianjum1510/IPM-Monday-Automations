/**
 * Placing a researched revenue figure into the board's revenue bands.
 *
 *   node --test test/
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseEnrichment } from '../src/lib/parse.js';
import { buildColumnValues } from '../src/lib/mapping.js';
import { bandForFigure, convert, parseBand, parseFigure, parseNumber } from '../src/lib/revenue.js';

const boards = JSON.parse(readFileSync(new URL('./boards.json', import.meta.url))).data.boards;
const warm = boards.find((b) => b.id === '5100825258');
const idOf = (board, title) => board.columns.find((c) => c.title === title)?.id;

/** Estimated Annual Revenue as it stands on the warm board. */
const EUR_BANDS = ['< 1M EUR', '1M-10M EUR', '10M-50M EUR', '50M-100M EUR', '100M-500M EUR', '500M+ EUR'];
const USD_BANDS = ['< 1M USD', '1M-10M USD', '10M-50M USD', '50M+ USD'];

/** The shape statusLabels() hands over: ids from 1, in board order. */
const options = (names) => names.map((label, i) => ({ index: i + 1, label }));
const bandOf = (names, figure, rates) => bandForFigure(options(names), figure, rates)?.label;

const RATES = { EUR: 1, USD: 1.25 };

test('the board labels read as half-open ranges', () => {
  assert.deepEqual(parseBand('< 1M EUR'), { min: 0, max: 1e6, currency: 'EUR' });
  assert.deepEqual(parseBand('1M-10M EUR'), { min: 1e6, max: 1e7, currency: 'EUR' });
  assert.deepEqual(parseBand('500M+ EUR'), { min: 5e8, max: Infinity, currency: 'EUR' });
  assert.deepEqual(parseBand('$10M - $50M'), { min: 1e7, max: 5e7, currency: 'USD' });
  assert.deepEqual(parseBand('10-50 Mio. €'), { min: 1e7, max: 5e7, currency: 'EUR' });
  assert.deepEqual(parseBand('Up to 1M EUR'), { min: 0, max: 1e6, currency: 'EUR' });
  assert.equal(parseBand('N/A'), null);
});

test('a figure on an edge goes to the band it opens, not the one it closes', () => {
  assert.equal(bandOf(EUR_BANDS, 'EUR 10,000,000'), '10M-50M EUR');
  assert.equal(bandOf(EUR_BANDS, 'EUR 1,000,000'), '1M-10M EUR', '"< 1M" leaves 1M out');
  assert.equal(bandOf(EUR_BANDS, 'EUR 999,999'), '< 1M EUR');
  assert.equal(bandOf(EUR_BANDS, 'EUR 500,000,000'), '500M+ EUR', '"500M+" takes 500M in');
});

test('the way companies write revenue is understood', () => {
  const cases = [
    ['EUR 30,000,000 (2024)', 30e6],
    ['€30 million', 30e6],
    ['30 Mio. EUR', 30e6],
    ['30,5 Mio. €', 30.5e6],
    ['1.500.000,00 €', 1.5e6],
    ['1,2 Mrd. EUR', 1.2e9],
    ['30.000 TEUR', 30e6],
    ['$1.2B', 1.2e9],
    ['Umsatz 2023: 30 Mio. EUR', 30e6],
    ['30-35 Mio. EUR', 32.5e6],
  ];
  for (const [text, amount] of cases) {
    assert.equal(parseFigure(text)?.amount, amount, text);
  }
});

test('a number with no scale is not mistaken for a revenue', () => {
  assert.equal(parseFigure('30'), null, 'a missing "million", not thirty euros');
  assert.equal(parseFigure('Not stated (2024)'), null);
  assert.equal(bandForFigure(options(EUR_BANDS), '30', RATES), null);
});

test('German and English separators', () => {
  assert.equal(parseNumber('30.000.000'), 30000000);
  assert.equal(parseNumber('30,000,000'), 30000000);
  assert.equal(parseNumber('1,2'), 1.2);
  assert.equal(parseNumber('1.5'), 1.5);
  assert.equal(parseNumber('30.000'), 30000);
});

test('a euro figure is converted before it is placed on a dollar board', () => {
  // 45M EUR is 56.25M USD: 10M-50M without the conversion, 50M+ with it.
  assert.equal(bandOf(USD_BANDS, 'EUR 45,000,000', RATES), '50M+ USD');

  const placed = bandForFigure(options(USD_BANDS), 'EUR 45,000,000', RATES);
  assert.equal(placed.from, 'EUR');
  assert.equal(placed.currency, 'USD');
  assert.equal(placed.amount, 56.25e6);
});

test('a dollar figure is converted before it is placed on a euro board', () => {
  // 62.5M USD is 50M EUR - exactly on the edge, so it opens 50M-100M.
  assert.equal(bandOf(EUR_BANDS, 'USD 62,500,000', RATES), '50M-100M EUR');
});

test('currency codes are whole words, except the T in TEUR', () => {
  assert.equal(parseFigure('Nokia 30 Mio. (no currency stated)')?.currency, '');
  assert.equal(parseFigure('30.000 TEUR')?.currency, 'EUR');
  assert.equal(parseFigure('US$ 30 million')?.currency, 'USD');
});

test('a figure with no currency is taken to be in the board currency', () => {
  assert.equal(bandOf(USD_BANDS, '45 million', RATES), '10M-50M USD');
});

test('no rate means no guess', () => {
  assert.equal(convert(30e6, 'GBP', 'EUR', RATES), null);
  assert.deepEqual(bandForFigure(options(EUR_BANDS), 'GBP 30,000,000', RATES), {
    reason: 'no exchange rate for GBP -> EUR',
  });
  assert.match(bandForFigure(options(EUR_BANDS), 'USD 30,000,000', null).reason, /no exchange rate/);
});

test('a column whose options are not numeric bands is left to text matching', () => {
  assert.match(bandForFigure(options(['GmbH', 'AG', 'KG']), 'EUR 30,000,000', RATES).reason, /not numeric bands/);
});

/** The warm board with its revenue options set, as the live column has them. */
const withRevenueOptions = (names) => ({
  ...warm,
  columns: warm.columns.map((column) =>
    column.title === 'Estimated Annual Revenue'
      ? { ...column, settings_str: JSON.stringify({ labels: names.map((name, i) => ({ id: i + 1, name })) }) }
      : column,
  ),
});

test('the figure decides the band, over the band the model picked', () => {
  const board = withRevenueOptions(EUR_BANDS);
  const fields = parseEnrichment(
    'ESTIMATED_ANNUAL_REVENUE: 1M-10M EUR\nANNUAL_REVENUE_FIGURE: EUR 30,000,000 (2024)',
  );
  const { values, banded, unmatched } = buildColumnValues(board.columns, fields);

  assert.deepEqual(values[idOf(board, 'Estimated Annual Revenue')], { ids: [3] }, '10M-50M EUR');
  assert.equal(banded[0].label, '10M-50M EUR');
  assert.deepEqual(unmatched, []);
  assert.match(
    values[idOf(board, 'Comments')].text,
    /Estimated Annual Revenue figure: EUR 30,000,000 \(2024\) - 30M EUR -> 10M-50M EUR/,
  );
});

test('with no figure, the band the model picked is used', () => {
  const board = withRevenueOptions(EUR_BANDS);
  const { values, banded } = buildColumnValues(
    board.columns,
    parseEnrichment('ESTIMATED_ANNUAL_REVENUE: 10M-50M EUR\nANNUAL_REVENUE_FIGURE: Not found'),
  );

  assert.deepEqual(values[idOf(board, 'Estimated Annual Revenue')], { ids: [3] });
  assert.deepEqual(banded, []);
});

test('a figure that cannot be placed falls back to the model band, and says why', () => {
  const board = withRevenueOptions(EUR_BANDS);
  const { values } = buildColumnValues(
    board.columns,
    parseEnrichment('ESTIMATED_ANNUAL_REVENUE: 10M-50M EUR\nANNUAL_REVENUE_FIGURE: GBP 30,000,000'),
    {},
    { rates: RATES, date: '2026-10-15' },
  );

  assert.deepEqual(values[idOf(board, 'Estimated Annual Revenue')], { ids: [3] });
  assert.match(values[idOf(board, 'Comments')].text, /not placed \(no exchange rate for GBP -> EUR\)/);
});

test('the conversion is spelled out in Comments', () => {
  const board = withRevenueOptions(USD_BANDS);
  const { values } = buildColumnValues(
    board.columns,
    parseEnrichment('ANNUAL_REVENUE_FIGURE: EUR 45,000,000 (2024)'),
    {},
    { rates: RATES, date: '2026-10-15' },
  );

  assert.deepEqual(values[idOf(board, 'Estimated Annual Revenue')], { ids: [4] }, '50M+ USD');
  assert.match(
    values[idOf(board, 'Comments')].text,
    /45M EUR = 56\.25M USD at ECB rate of 2026-10-15 -> 50M\+ USD/,
  );
});

test('the prompt asks for the raw figure', async () => {
  const { buildPrompt } = await import('../src/lib/prompt.js');
  assert.match(buildPrompt('Muster GmbH', 'Badstraße 115, 71336 Waiblingen'), /ANNUAL_REVENUE_FIGURE: \[/);
});
