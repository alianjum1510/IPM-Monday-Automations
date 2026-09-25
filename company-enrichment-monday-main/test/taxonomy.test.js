/**
 * The board_relation columns: Industry and Job Function.
 *
 * Both link to items on a separate taxonomy board, and the board's mirrors read
 * Industry Score / Role Score / Department / Hauptbrachen through that link into
 * Initial Lead Score. Enrichment used to leave both blank, so those mirrors were
 * empty and every enriched lead scored on incomplete inputs.
 *
 * taxonomy.json is a slice of the real boards, so the names here are spelled the
 * way the live taxonomy spells them - German, bracketed, and in four cases
 * duplicated with different scores behind each copy.
 *
 *   node --test test/
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseEnrichment } from '../src/lib/parse.js';
import { buildColumnValues } from '../src/lib/mapping.js';
import { connectedBoardId, matchTaxonomyItem, taxonomyChoices } from '../src/lib/taxonomy.js';
import { buildPrompt } from '../src/lib/prompt.js';

const taxonomy = JSON.parse(readFileSync(new URL('./taxonomy.json', import.meta.url)));
const { industries, jobFunctions } = taxonomy;

const boards = JSON.parse(readFileSync(new URL('./boards.json', import.meta.url))).data.boards;
const warm = boards.find((b) => b.id === '5100825258');
const cold = boards.find((b) => b.id === '5100463291');

const idOf = (board, title) => board.columns.find((c) => c.title === title)?.id;

/**
 * boards.json predates `settings_str` in the board query, so the connected
 * board ids are attached here. The cold board's Industry column really does
 * carry only `boardIds` with no `boardId` key - that asymmetry is the point of
 * the test below.
 */
const withRelationSettings = (board, industrySettings) => ({
  ...board,
  columns: board.columns.map((column) => {
    if (column.title === 'Industry') return { ...column, settings_str: JSON.stringify(industrySettings) };
    if (column.title === 'Job Function') {
      return { ...column, settings_str: JSON.stringify({ boardIds: [Number(taxonomy.jobFunctionBoardId)] }) };
    }
    return column;
  }),
});

/** columnId -> taxonomy items, as enrichment.js assembles it before the write. */
const relationsFor = (board) => ({
  [idOf(board, 'Industry')]: industries,
  [idOf(board, 'Job Function')]: jobFunctions,
});

const ANSWER = (industry, jobFunction) => `
CORRECT_NAME: Muster Großhandel GmbH
CONTACT_NAME: Michael Dietzel
INDUSTRY: ${industry}
JOB_FUNCTION: ${jobFunction}
`;

test('the researched industry and job function are linked by item id', () => {
  const fields = parseEnrichment(ANSWER('Industrie & Produktion', 'Vertriebsleiter (CSO)'));
  const { values, linked } = buildColumnValues(warm.columns, fields, relationsFor(warm));

  assert.deepEqual(values[idOf(warm, 'Industry')], { item_ids: ['2820930311'] });
  assert.deepEqual(values[idOf(warm, 'Job Function')], { item_ids: ['2872722273'] });

  assert.deepEqual(
    linked.map((entry) => `${entry.title}=${entry.name}`),
    ['Industry=Industrie & Produktion', 'Job Function=Vertriebsleiter (CSO)'],
  );
});

test('both boards get linked, though the columns have different ids', () => {
  const fields = parseEnrichment(ANSWER('Transport & Logistik', 'Geschäftsführung'));

  for (const board of [warm, cold]) {
    const { values } = buildColumnValues(board.columns, fields, relationsFor(board));
    assert.deepEqual(values[idOf(board, 'Industry')], { item_ids: ['2820930278'] });
    assert.deepEqual(values[idOf(board, 'Job Function')], { item_ids: ['2872725350'] });
  }
});

test('a name the taxonomy does not have is never invented, and survives in Comments', () => {
  const fields = parseEnrichment(ANSWER('Software & SaaS', 'Chief Happiness Officer'));
  const { values, skipped, unmatched } = buildColumnValues(warm.columns, fields, relationsFor(warm));

  // Nothing written: a relation has no "N/A" to fall back on.
  assert.equal(values[idOf(warm, 'Industry')], undefined);
  assert.equal(values[idOf(warm, 'Job Function')], undefined);
  assert.ok(skipped.includes('Industry'));
  assert.ok(skipped.includes('Job Function'));

  // But the research is not lost.
  const comments = values[idOf(warm, 'Comments')].text;
  assert.match(comments, /Industry \(no matching option\): Software & SaaS/);
  assert.match(comments, /Job Function \(no matching option\): Chief Happiness Officer/);

  assert.deepEqual(
    unmatched.map((e) => e.title).filter((t) => t === 'Industry' || t === 'Job Function').sort(),
    ['Industry', 'Job Function'],
  );
});

test('"Not found" is treated as no answer, not as a value to match', () => {
  const fields = parseEnrichment(ANSWER('Not found', 'Not found'));
  const { values, skipped, unmatched } = buildColumnValues(warm.columns, fields, relationsFor(warm));

  assert.equal(values[idOf(warm, 'Industry')], undefined);
  assert.ok(skipped.includes('Industry'));
  // Nothing was researched, so there is nothing to report to a human either.
  assert.equal(unmatched.filter((e) => e.title === 'Industry' || e.title === 'Job Function').length, 0);
});

test('with no taxonomy loaded the columns are skipped, not broken', () => {
  const fields = parseEnrichment(ANSWER('Industrie & Produktion', 'Geschäftsführung'));
  const { values, skipped } = buildColumnValues(warm.columns, fields);

  assert.equal(values[idOf(warm, 'Industry')], undefined);
  assert.ok(skipped.includes('Industry'));
  // The rest of the write is untouched.
  assert.equal(values[idOf(warm, 'Company / Customer Name')], 'Muster Großhandel GmbH');
});

test('a model that drops the bracketed detail still matches', () => {
  const m = matchTaxonomyItem(industries, 'Großhandel');
  assert.equal(
    m.name,
    'Großhandel (Industrie-; Arbeitsschutz-; Hygiene-; Auto-; Farb-; Bau-; Medizin- und Sanitärgroßhandel)',
  );
  assert.equal(matchTaxonomyItem(jobFunctions, 'Finanzvorstand').name, 'Finanzvorstand (CFO)');
});

test('German is matched through "&"/"und", umlauts and casing', () => {
  assert.equal(matchTaxonomyItem(industries, 'industrie und produktion').name, 'Industrie & Produktion');
  assert.equal(matchTaxonomyItem(industries, 'BANKEN & VERSICHERUNGEN').name, 'Banken & Versicherungen');
  assert.equal(matchTaxonomyItem(jobFunctions, 'geschaeftsfuehrung').name, 'Geschäftsführung');
});

/**
 * Four names exist twice on the Job Function board with different Role Scores
 * behind them - "Geschäftsführer" is 13 on one and 10 on the other. An unstable
 * tie-break would make the lead score depend on the order monday returned rows
 * in, so the oldest item wins and the collision is reported.
 */
test('a duplicated taxonomy name resolves to the oldest item, and is reported', () => {
  const m = matchTaxonomyItem(jobFunctions, 'Geschäftsführer');

  assert.equal(m.id, '2872722656');
  assert.deepEqual(m.ambiguous, ['2872722656', '2872726857']);
  assert.equal(matchTaxonomyItem(jobFunctions, 'Geschäftsführer').id, m.id, 'must be stable');
});

test('the collision reaches the caller so the run log can name it', () => {
  const fields = parseEnrichment(ANSWER('Handel & Vertrieb', 'Scrum Master'));
  const { ambiguous } = buildColumnValues(warm.columns, fields, relationsFor(warm));

  assert.equal(ambiguous.length, 1);
  assert.equal(ambiguous[0].title, 'Job Function');
  assert.equal(ambiguous[0].ids.length, 2);
});

/**
 * "Handel" sits inside Großhandel, Einzelhandel and Onlinehandel. Picking one of
 * those would write a score nobody chose, and silently - a wrong link is worse
 * than no link, because no link is logged and kept in Comments.
 */
test('a substring is not enough to link a lead to an industry', () => {
  // Inside "Chemie- & Pharmaindustrie", but not a prefix of it.
  assert.equal(matchTaxonomyItem(industries, 'Pharma'), null);
  assert.equal(matchTaxonomyItem(industries, 'Logistik'), null);

  // A prefix, but mid-word: four characters must not pick an Industry Score.
  assert.equal(matchTaxonomyItem(industries, 'Auto'), null);
  assert.equal(matchTaxonomyItem(industries, 'Groß'), null);

  // A prefix ending on a word boundary is still allowed - and flagged when it
  // lands on more than one row.
  assert.ok(matchTaxonomyItem(industries, 'Handel').ambiguous.length > 0);
});

test('every real taxonomy name resolves to itself', () => {
  for (const items of [industries, jobFunctions]) {
    for (const item of items) {
      const m = matchTaxonomyItem(items, item.name);
      assert.ok(m, `no match for ${item.name}`);
      assert.equal(m.name.toLowerCase(), item.name.toLowerCase());
    }
  }
});

test('an empty or absent taxonomy matches nothing rather than throwing', () => {
  assert.equal(matchTaxonomyItem([], 'Industrie & Produktion'), null);
  assert.equal(matchTaxonomyItem(undefined, 'Industrie & Produktion'), null);
  assert.equal(matchTaxonomyItem(industries, ''), null);
});

/** The cold board's Industry column carries boardIds with no boardId key. */
test('the connected board is read from boardIds, not boardId', () => {
  assert.equal(connectedBoardId({ settings_str: '{"boardIds":[5094116229]}' }), '5094116229');
  assert.equal(
    connectedBoardId({ settings_str: '{"boardIds":[5094116229],"boardId":5094116229}' }),
    '5094116229',
  );
  // Nothing configured, or unparsable - no board, and no crash.
  assert.equal(connectedBoardId({ settings_str: '{}' }), '');
  assert.equal(connectedBoardId({ settings_str: 'not json' }), '');
  assert.equal(connectedBoardId(undefined), '');
});

test('the choices handed to the model come from the board the column points at', () => {
  const board = withRelationSettings(warm, { boardIds: [Number(taxonomy.industryBoardId)] });
  const relations = relationsFor(board);

  const chosen = taxonomyChoices(relations, board.columns, 'Industry');
  assert.equal(chosen.length, industries.length);
  assert.ok(chosen.includes('Industrie & Produktion'));

  // De-duplicated, so the model never sees the collision.
  const roles = taxonomyChoices(relations, board.columns, 'Job Function');
  assert.equal(roles.length, new Set(roles).size);
  assert.ok(roles.length < jobFunctions.length, 'the duplicate names should collapse');

  assert.deepEqual(taxonomyChoices(relations, board.columns, 'No Such Column'), []);
});

test('the prompt asks for the two fields, quoting the list verbatim', () => {
  const prompt = buildPrompt('Muster GmbH', 'Musterstr. 1, 10115 Berlin', {
    industries: industries.map((i) => i.name),
    jobFunctions: jobFunctions.map((i) => i.name),
  });

  assert.match(prompt, /^INDUSTRY - choose exactly one/m);
  assert.match(prompt, /^JOB_FUNCTION - the role of the person named in CONTACT_NAME/m);
  assert.ok(prompt.includes('- Industrie & Produktion'));
  assert.ok(
    prompt.includes('- Großhandel (Industrie-; Arbeitsschutz-; Hygiene-; Auto-; Farb-; Bau-; Medizin- und Sanitärgroßhandel)'),
    'the bracketed name must be quoted in full, or the model cannot echo it back',
  );
  assert.match(prompt, /Do NOT translate, abbreviate, reword or invent a value/);

  // The master prompt is still intact ahead of the new section.
  assert.ok(prompt.includes('CRITICAL INSTRUCTION: You MUST perform AT LEAST 15-20 web searches'));
  assert.ok(prompt.indexOf('EXTRA FIELDS') < prompt.indexOf('CLASSIFICATION FIELDS'));
});

test('with no taxonomy the prompt does not invite the model to make one up', () => {
  const prompt = buildPrompt('Muster GmbH', 'Musterstr. 1', {});

  assert.ok(!prompt.includes('CLASSIFICATION FIELDS'));
  assert.ok(!prompt.includes('INDUSTRY -'));
  // Unchanged from the build that had no relation support at all.
  assert.equal(prompt, buildPrompt('Muster GmbH', 'Musterstr. 1'));
});
