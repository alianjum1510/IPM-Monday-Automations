/**
 * The country is classified from the user's input before the research runs.
 *
 *   node --test test/
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { countryCode, countryFromInput } from '../src/lib/country.js';

const codeOf = (column, address) => countryFromInput(column, address)?.code ?? null;

test('the Country column decides first, in any language or as a code', () => {
  assert.equal(codeOf('Germany', 'Ringstraße 1, 1010 Wien, Austria'), 'DE');
  assert.equal(codeOf('Österreich', ''), 'AT');
  assert.equal(codeOf('CH', ''), 'CH');
  assert.equal(countryFromInput('Germany', '').source, 'Country column');
});

test('a country name in the address classifies the lead', () => {
  const cases = {
    'Badstraße 115, 71336 Waiblingen, Deutschland': 'DE',
    'Ringstraße 1, 1010 Wien, Österreich': 'AT',
    'Ringstraße 1, 1010 Wien Österreich': 'AT',
    'Bahnhofstrasse 1, 8001 Zürich, Schweiz': 'CH',
    'Damrak 1, 1012 Amsterdam, Nederland': 'NL',
    'Rue de Rivoli 1, 75001 Paris, France': 'FR',
    'ul. Marszałkowska 1, 00-001 Warszawa, Polska': 'PL',
    '1 Main St, Springfield, IL 62701, USA': 'US',
    'Main Street 1, Dublin, Ireland': 'IE',
  };
  for (const [address, code] of Object.entries(cases)) {
    assert.equal(codeOf('', address), code, address);
  }
});

test('a postal prefix classifies the lead', () => {
  assert.equal(codeOf('', 'Badstraße 115, D-71336 Waiblingen'), 'DE');
  assert.equal(codeOf('', 'Ringstraße 1, A-1010 Wien'), 'AT');
  assert.equal(codeOf('', 'Bahnhofstrasse 1, CH-8001 Zürich'), 'CH');
  assert.equal(countryFromInput('', 'Ringstraße 1, A-1010 Wien').source, 'postal prefix in address');
});

test('a country word inside the street does not classify the lead', () => {
  assert.equal(codeOf('', 'Schweizer Straße 3, 60594 Frankfurt'), null);
  assert.equal(codeOf('', 'Frankreichstraße 2, 10115 Berlin'), null);
});

test('an address with only a city is left for the model to place', () => {
  assert.equal(codeOf('', 'Badstraße 115, 71336 Waiblingen'), null);
  assert.equal(codeOf('', ''), null);
});

test('the model\'s one-word answer is validated as a real country code', () => {
  assert.equal(countryCode('AT'), 'AT');
  assert.equal(countryCode('UNKNOWN'), '');
  assert.equal(countryCode('ZZ'), '');
  assert.equal(countryCode(''), '');
});
