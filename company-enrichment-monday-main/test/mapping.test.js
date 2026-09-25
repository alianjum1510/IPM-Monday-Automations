/**
 * Runs the parser + mapper against the real column schemas of both boards.
 *
 *   node --test test/
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseEnrichment } from '../src/lib/parse.js';
import {
  buildColumnValues,
  mayAdvanceStage,
  NA_TEXT,
  LIFECYCLE_STAGE_ENRICHED,
  LIFECYCLE_STAGE_TITLE,
} from '../src/lib/mapping.js';

const boards = JSON.parse(readFileSync(new URL('./boards.json', import.meta.url))).data.boards;
const warm = boards.find((b) => b.id === '5100825258');
const cold = boards.find((b) => b.id === '5100463291');

const titleOf = (board, id) => board.columns.find((c) => c.id === id)?.title;
const idOf = (board, title) => board.columns.find((c) => c.title === title)?.id;

const FULL_ANSWER = `
CORRECT_NAME: ANDREAS STIHL AG & Co. KG
CORRECT_ADDRESS: Badstraße 115, 71336 Waiblingen, Deutschland
CLASSIFICATION: private
REGISTRATION_NUMBER: HRA 260269
HRB_CONFIDENCE: HIGH (handelsregister.de)
REGISTRY_COURT: Amtsgericht Stuttgart
VERIFICATION_SOURCE: https://www.stihl.de/impressum
REGISTRY_SOURCE: https://www.handelsregister.de
UID_NUMBER: DE146214838
VAT_CONFIDENCE: HIGH (company Impressum page)
HOMEPAGE: www.stihl.de
HANDELSREGISTER_VERIFIED: Yes
COMPANY_STATUS: Active (companyhouse.de)
LINKEDIN_PROFILE: https://www.linkedin.com/company/stihl
CONFIDENCE: High
NOTES: 21 searches performed. Parent of STIHL Vertriebszentrale AG & Co. KG.
ADDRESS_LINE_1: Badstraße 115
ADDRESS_LINE_2: Not found
ADDRESS_LINE_3: Not found
POSTAL_CODE: 71336
CITY: Waiblingen
STATE: Baden-Württemberg
DISTRICT: Rems-Murr-Kreis
COUNTRY: Germany
COUNTRY_CODE: DE
COMPANY_EMAIL: info@stihl.de
MAIN_PHONE: +49 7151 26 0
MOBILE_NUMBER: Not found
FAX: +49 7151 26 1080
PHONE_TYPE: Landline
CONTACT_NAME: Dr. Michael Prochaska
COMPANY_SIZE: 20,000
ESTIMATED_ANNUAL_REVENUE: 1B+ EUR
COMPANY_STRUCTURE: AG & Co. KG
OWNERSHIP_TYPE: Private
D_AND_B_NUMBER: 315744159
`;

test('the email lands in Company Email, never in Email', () => {
  for (const board of [warm, cold]) {
    const { values } = buildColumnValues(board.columns, parseEnrichment(FULL_ANSWER));

    const companyEmailId = idOf(board, 'Company Email');
    assert.deepEqual(values[companyEmailId], { email: 'info@stihl.de', text: 'info@stihl.de' });

    assert.equal(values[idOf(board, 'Email')], undefined, 'lead_email must be left alone');
    assert.equal(values.lead_email, undefined);
  }
});

test('typed columns get monday-shaped values', () => {
  const { values } = buildColumnValues(warm.columns, parseEnrichment(FULL_ANSWER));

  assert.equal(values[idOf(warm, 'Company / Customer Name')], 'ANDREAS STIHL AG & Co. KG');
  assert.equal(values[idOf(warm, 'Registration Number')], 'HRA 260269');
  assert.equal(values[idOf(warm, 'Postal Code')], '71336');
  assert.deepEqual(values[idOf(warm, 'Country')], { countryCode: 'DE', countryName: 'Germany' });
  assert.deepEqual(values[idOf(warm, 'Main Phone')], { phone: '+497151260', countryShortName: 'DE' });
  assert.deepEqual(values[idOf(warm, 'Website')], { url: 'https://www.stihl.de', text: 'www.stihl.de' });
  assert.equal(values[idOf(warm, 'Company Size')], '20000', 'thousands separator stripped');
  assert.deepEqual(values[idOf(warm, 'Phone Type')], { labels: ['Landline'] });
});

test('the VAT number and confidences survive in Comments', () => {
  const { values } = buildColumnValues(warm.columns, parseEnrichment(FULL_ANSWER));
  const comments = values[idOf(warm, 'Comments')].text;

  assert.match(comments, /VAT \(USt-IdNr\): DE146214838/);
  assert.match(comments, /HRB confidence: HIGH \(handelsregister\.de\)/);
  assert.match(comments, /Registry court: Amtsgericht Stuttgart/);
  assert.match(comments, /21 searches performed/);
});

test('empty text and dropdown columns are filled with N/A', () => {
  const sparse = parseEnrichment(`
CORRECT_NAME: Kleine Firma GmbH
REGISTRATION_NUMBER: Not found after extensive search
CITY: Berlin
COUNTRY: Not found
COMPANY_EMAIL: Not found
MAIN_PHONE: Not found
COMPANY_SIZE: Not found
OWNERSHIP_TYPE: Not found
`);

  const { values, filled, skipped } = buildColumnValues(warm.columns, sparse);

  assert.equal(values[idOf(warm, 'Registration Number')], NA_TEXT);
  assert.equal(values[idOf(warm, 'Address Line 1')], NA_TEXT);
  assert.equal(values[idOf(warm, 'District')], NA_TEXT);
  assert.deepEqual(values[idOf(warm, 'Ownership Type')], { labels: [NA_TEXT] });
  assert.equal(values[idOf(warm, 'City')], 'Berlin', 'a real value is not overwritten with N/A');

  // The columns that sat blank in the board screenshot.
  assert.deepEqual(values[idOf(warm, 'LinkedIn Profile')], { url: NA_TEXT, text: NA_TEXT });
  assert.deepEqual(values[idOf(warm, 'Website')], { url: NA_TEXT, text: NA_TEXT });
  assert.deepEqual(values[idOf(warm, 'Mobile Number')], { phone: NA_TEXT, countryShortName: '' });
  assert.deepEqual(values[idOf(warm, 'Company Email')], { email: NA_TEXT, text: NA_TEXT });

  for (const title of ['LinkedIn Profile', 'Website', 'Mobile Number', 'Company Email']) {
    assert.ok(filled.includes(title), `${title} should be N/A-filled`);
  }

  // Number, date and country columns have nowhere to keep the string "N/A".
  for (const title of ['Company Size', 'Country']) {
    assert.equal(values[idOf(warm, title)], undefined, `${title} must stay empty`);
    assert.ok(skipped.includes(title), `${title} should be reported as skipped`);
  }
  assert.ok(filled.includes('Registration Number'));
});

test('placeholder echoes and "not found" phrasings normalise to empty', () => {
  const fields = parseEnrichment(`
CORRECT_NAME: [legal name]
REGISTRATION_NUMBER: Not found after extensive search
UID_NUMBER: N/A
HANDELSREGISTER_VERIFIED: No
CITY: Hamburg
`);

  assert.equal(fields.CORRECT_NAME, '');
  assert.equal(fields.REGISTRATION_NUMBER, '');
  assert.equal(fields.UID_NUMBER, '');
  assert.equal(fields.HANDELSREGISTER_VERIFIED, 'No', 'a real "No" answer is kept');
  assert.equal(fields.CITY, 'Hamburg');
});

test('multi-line NOTES are kept whole', () => {
  const fields = parseEnrichment(`
NOTES: First line of notes.
Second line continues here.
CITY: Köln
`);

  assert.equal(fields.NOTES, 'First line of notes. Second line continues here.');
  assert.equal(fields.CITY, 'Köln');
});

/**
 * boards.json predates `settings_str` in the board query, so the label lists
 * are built here. The warm list mirrors the board as it stands: the capital-A
 * label the board has always had, plus the lowercase duplicate an earlier
 * build's `create_labels_if_missing` write invented at index 106.
 */
const withStageLabels = (board, labels) => ({
  ...board,
  columns: board.columns.map((column) =>
    column.title === LIFECYCLE_STAGE_TITLE
      ? { ...column, settings_str: JSON.stringify({ labels }) }
      : column,
  ),
});

const WARM_STAGE_LABELS = {
  0: 'Inbound',
  1: 'Data Authentication Required',
  2: 'Discovery Booked',
  3: 'Data Complete',
  4: 'Disqualified',
  5: 'Nurture List',
  6: 'Short Route- Discovery',
  106: 'Data authentication required',
};

test('the stage reuses the board label that differs only in casing', () => {
  const board = withStageLabels(warm, WARM_STAGE_LABELS);
  const { values } = buildColumnValues(board.columns, parseEnrichment(FULL_ANSWER));

  // Index 1, not 106: the board's own label, never the duplicate.
  assert.deepEqual(values[idOf(board, LIFECYCLE_STAGE_TITLE)], { index: 1 });
});

test('the stage is written by index, so no label can ever be created', () => {
  const board = withStageLabels(warm, WARM_STAGE_LABELS);
  const { values } = buildColumnValues(board.columns, parseEnrichment(FULL_ANSWER));
  const written = values[idOf(board, LIFECYCLE_STAGE_TITLE)];

  assert.equal(written.label, undefined, 'a label string would let monday invent one');
  assert.ok(Number.isInteger(written.index));
});

test('a renamed stage label is still found by its prefix', () => {
  const board = withStageLabels(warm, { 0: 'Inbound', 4: 'Data Authentication Pending' });
  const { values } = buildColumnValues(board.columns, parseEnrichment(FULL_ANSWER));

  assert.deepEqual(values[idOf(board, LIFECYCLE_STAGE_TITLE)], { index: 4 });
});

test('an unrecognisable stage column is left alone rather than guessed at', () => {
  const board = withStageLabels(warm, { 0: 'Inbound', 1: 'Discovery Booked' });
  const { values, skipped } = buildColumnValues(board.columns, parseEnrichment(FULL_ANSWER));

  assert.equal(values[idOf(board, LIFECYCLE_STAGE_TITLE)], undefined);
  assert.ok(skipped.includes(LIFECYCLE_STAGE_TITLE));
});

test('a stage column with no settings at all cannot break the write', () => {
  // boards.json as-is: no settings_str on any column.
  const { values, skipped } = buildColumnValues(warm.columns, parseEnrichment(FULL_ANSWER));

  assert.equal(values[idOf(warm, LIFECYCLE_STAGE_TITLE)], undefined);
  assert.ok(skipped.includes(LIFECYCLE_STAGE_TITLE));
  assert.ok(Object.keys(values).length >= 20, 'the rest of the write is unaffected');
});

/**
 * The stage guard. A run takes minutes, so the lead can move while it is in
 * flight - these are the stages the finished run may and may not write over.
 */
test('a lead still waiting on enrichment has its stage advanced', () => {
  assert.ok(mayAdvanceStage(''), 'no stage at all');
  assert.ok(mayAdvanceStage('Inbound'));
  assert.ok(mayAdvanceStage('Data Authentication Required'), 'a re-run');
  assert.ok(mayAdvanceStage('data authentication required'), 'the casing duplicate');
  assert.ok(mayAdvanceStage('Data Authentication Pending'), 'renamed, still the same stage');
});

test('a lead that moved on during the run keeps its stage', () => {
  // The reported bug: booked a call mid-run, finished run pulled it back.
  assert.equal(mayAdvanceStage('Discovery Booked'), false);

  for (const stage of ['Data Complete', 'Disqualified', 'Nurture List', 'Short Route- Discovery']) {
    assert.equal(mayAdvanceStage(stage), false, `${stage} must not be overwritten`);
  }
});

test('a downstream stage added to the board later is protected by default', () => {
  // An allowlist, so a label nobody told this app about is held, not overwritten.
  assert.equal(mayAdvanceStage('Contract Sent'), false);
});

test('a board whose leads arrive on another stage can say so', () => {
  assert.ok(mayAdvanceStage('New Lead', ['New Lead', LIFECYCLE_STAGE_ENRICHED]));
  assert.equal(mayAdvanceStage('Inbound', ['New Lead']), false, 'the override replaces the default');
});

test('the stage moves for a sparse answer too', () => {
  const board = withStageLabels(cold, WARM_STAGE_LABELS);
  const { values } = buildColumnValues(board.columns, parseEnrichment('CORRECT_NAME: Kleine Firma GmbH'));

  assert.deepEqual(values[idOf(board, LIFECYCLE_STAGE_TITLE)], { index: 1 });
});

/** The dropdown shape of settings_str, which differs from status. */
const withDropdownLabels = (board, title, names) => ({
  ...board,
  columns: board.columns.map((column) =>
    column.title === title
      ? {
          ...column,
          settings_str: JSON.stringify({
            labels: names.map((name, i) => ({ id: i + 1, name })),
          }),
        }
      : column,
  ),
});

const DIALLING_CODES = ['+1', '+20', '+212', '+213', '+216', '+43', '+49', '+92'];

test('web_search citations are stripped from the data fields', () => {
  const fields = parseEnrichment(`
CONTACT_NAME: Michael Dietzel; Boris Sobot — Vorstand ([svg-sued.de](https://www.svg-sued.de/impressum?utm_source=openai))
HOMEPAGE: [www.svg-sued.de](https://www.svg-sued.de?utm_source=openai)
CORRECT_NAME: SVG Süd GmbH ([handelsregister.de](https://www.handelsregister.de))
`);

  assert.equal(fields.CONTACT_NAME, 'Michael Dietzel; Boris Sobot — Vorstand');
  assert.equal(fields.HOMEPAGE, 'www.svg-sued.de');
  assert.equal(fields.CORRECT_NAME, 'SVG Süd GmbH');
});

test('the verification trail keeps its sources', () => {
  const fields = parseEnrichment(`
HRB_CONFIDENCE: HIGH (handelsregister.de)
COMPANY_STATUS: Active (companyhouse.de)
VAT_CONFIDENCE: HIGH (company Impressum page)
VERIFICATION_SOURCE: https://www.stihl.de/impressum?utm_source=openai
`);

  assert.equal(fields.HRB_CONFIDENCE, 'HIGH (handelsregister.de)');
  assert.equal(fields.COMPANY_STATUS, 'Active (companyhouse.de)');
  assert.equal(fields.VAT_CONFIDENCE, 'HIGH (company Impressum page)');
  assert.equal(fields.VERIFICATION_SOURCE, 'https://www.stihl.de/impressum', 'utm stripped');
});

test('Country Code gets the dialling code, taken from the phone number', () => {
  const board = withDropdownLabels(warm, 'Country Code', DIALLING_CODES);
  const { values } = buildColumnValues(board.columns, parseEnrichment(FULL_ANSWER));

  assert.deepEqual(values[idOf(board, 'Country Code')], { labels: ['+49'] });
});

test('a longer dialling code is not swallowed by a shorter one', () => {
  const board = withDropdownLabels(warm, 'Country Code', DIALLING_CODES);
  const fields = parseEnrichment('COUNTRY: Morocco\nCOUNTRY_CODE: MA\nMAIN_PHONE: +212 522 123456');

  const { values } = buildColumnValues(board.columns, fields);
  assert.deepEqual(values[idOf(board, 'Country Code')], { labels: ['+212'] }, 'not +21 or +2');
});

test('with no phone at all the dialling code comes from the ISO code', () => {
  const board = withDropdownLabels(warm, 'Country Code', DIALLING_CODES);
  const { values } = buildColumnValues(board.columns, parseEnrichment('COUNTRY_CODE: DE'));

  assert.deepEqual(values[idOf(board, 'Country Code')], { labels: ['+49'] });
});

test('the ISO code still goes to the country column', () => {
  const board = withDropdownLabels(warm, 'Country Code', DIALLING_CODES);
  const { values } = buildColumnValues(board.columns, parseEnrichment(FULL_ANSWER));

  assert.deepEqual(values[idOf(board, 'Country')], { countryCode: 'DE', countryName: 'Germany' });
});

test('a dropdown option is never invented, and the value survives in Comments', () => {
  const board = withDropdownLabels(
    withStageLabels(warm, WARM_STAGE_LABELS),
    'Estimated Annual Revenue',
    ['0-1M EUR', '1M-10M EUR'],
  );
  const { values, unmatched } = buildColumnValues(board.columns, parseEnrichment(FULL_ANSWER));

  // "1B+ EUR" is not on the list - N/A, not a new option.
  assert.deepEqual(values[idOf(board, 'Estimated Annual Revenue')], { labels: [NA_TEXT] });
  assert.deepEqual(unmatched, [{ title: 'Estimated Annual Revenue', value: '1B+ EUR' }]);
  assert.match(
    values[idOf(board, 'Comments')].text,
    /Estimated Annual Revenue \(no matching option\): 1B\+ EUR/,
  );
});

test('a dropdown with no list of its own still takes free text', () => {
  // boards.json has no settings_str, so every dropdown is unconstrained.
  const { values } = buildColumnValues(warm.columns, parseEnrichment(FULL_ANSWER));

  assert.deepEqual(values[idOf(warm, 'Phone Type')], { labels: ['Landline'] });
});

test('every planned column exists on at least one board', () => {
  const { values } = buildColumnValues(cold.columns, parseEnrichment(FULL_ANSWER));
  const written = Object.keys(values).map((id) => titleOf(cold, id));

  assert.ok(written.includes('Company Email'));
  assert.ok(written.length >= 20, `expected a full write, got ${written.length} columns`);
});
