"""
The researched company name and Company / Customer Name 2.

customer_name_split cuts a long name at MAX_NAME_LENGTH and moves the rest into
Company / Customer Name 2. Enrichment then researches the WHOLE name and writes
the researched one back split the same way - emptying Name 2 when it fits - or,
when nothing usable was researched, leaves both columns as they were.

  pytest
"""
import json
from pathlib import Path

import pytest

from app.core.name_split import split_customer_name
from app.features.company_enrichment.lib.mapping import NAME_OVERFLOW_TITLE, NAME_TITLE, build_column_values
from app.features.company_enrichment.lib.parse import parse_enrichment
from app.features.company_enrichment.services import enrichment

boards = json.loads((Path(__file__).parent / 'boards.json').read_text())['data']['boards']
warm = next(b for b in boards if b['id'] == '5100825258')

# The dev copy's overflow column (5106281544).
OVERFLOW = {'id': 'text_mm7qvqph', 'title': NAME_OVERFLOW_TITLE, 'type': 'text', 'settings_str': '{}'}
WITH_OVERFLOW = [*warm['columns'], OVERFLOW]
NAME_ID = next(c['id'] for c in warm['columns'] if c['title'] == NAME_TITLE)

LONG = 'Bayerische Maschinenbau und Anlagentechnik Aktiengesellschaft Zweigniederlassung München Nord Entwicklungszentrum Garching'
PART1 = 'Bayerische Maschinenbau und Anlagentechnik Aktiengesellschaft Zweigniederlassung München Nord'
PART2 = 'Entwicklungszentrum Garching'


def written(answer, columns=WITH_OVERFLOW, **kwargs):
    return build_column_values(columns, parse_enrichment(answer), **kwargs)


def test_a_researched_name_that_fits_empties_name_2():
    result = written('CORRECT_NAME: ANDREAS STIHL AG & Co. KG')
    assert result['values'][NAME_ID] == 'ANDREAS STIHL AG & Co. KG'
    assert result['values'][OVERFLOW['id']] == '', 'the old overflow belongs to the old name'
    assert result['name_split'] == {'name_chars': 25, 'overflow': ''}


def test_a_researched_name_over_100_is_split_like_the_name_split_does():
    name = 'Rheinisch-Westfälische Elektrizitäts- und Energieversorgungsgesellschaft AG Kundenservicezentrum Essen Nord'
    assert len(name) == 107
    result = written(f'CORRECT_NAME: {name}')
    expected = split_customer_name(name)
    assert result['values'][NAME_ID] == expected.part1 == (
        'Rheinisch-Westfälische Elektrizitäts- und Energieversorgungsgesellschaft AG Kundenservicezentrum'
    )
    assert result['values'][OVERFLOW['id']] == expected.part2 == 'Essen Nord'
    assert result['name_split'] == {'name_chars': 96, 'overflow': 'Essen Nord'}


def test_the_limit_follows_max_name_length():
    result = written('CORRECT_NAME: Muster Handel und Service Nord West', max_name_length=20)
    assert result['values'][NAME_ID] == 'Muster Handel und'
    assert result['values'][OVERFLOW['id']] == 'Service Nord West'


@pytest.mark.parametrize('answer', [
    'CORRECT_NAME: Not found',
    'CORRECT_NAME: [legal name]',
    'CITY: Waiblingen',  # no name in the answer at all
    f"CORRECT_NAME: {'X' * 60} {'Y' * 70}",  # over parse.py's 120 - not trusted as a name
])
def test_no_usable_name_keeps_the_leads_name_and_name_2(answer):
    result = written(answer)
    assert NAME_ID not in result['values'], 'never N/A over the real name'
    assert OVERFLOW['id'] not in result['values']
    assert NAME_TITLE in result['skipped']
    assert result['name_split'] is None


def test_without_name_2_the_researched_name_is_written_whole_as_before():
    name = 'Internationale Gesellschaft für Logistik, Lagerhaltung und Transportdienstleistungen Nord-West Europa GmbH'
    assert 100 < len(name) <= 120
    result = written(f'CORRECT_NAME: {name}', columns=warm['columns'])
    assert result['values'][NAME_ID] == name
    assert result['name_split'] is None


def test_a_long_text_name_2_is_cleared_in_its_own_shape():
    columns = [*warm['columns'], {**OVERFLOW, 'type': 'long_text'}]
    result = written('CORRECT_NAME: ANDREAS STIHL AG & Co. KG', columns=columns)
    assert result['values'][OVERFLOW['id']] == {'text': ''}


def test_other_columns_still_get_n_a():
    result = written('CORRECT_NAME: Not found')
    assert 'City' in result['filled'], 'only the name is kept; empty fields elsewhere are still N/A'


@pytest.fixture
def run(monkeypatch):
    """enrich_item with monday, OpenAI and the taxonomies faked; records the prompt and the write."""
    seen = {}
    item = {
        'id': '42', 'name': 'Item', 'state': 'active', 'board': {'id': '5106281544'},
        'column_values': [{'id': NAME_ID, 'text': PART1}, {'id': OVERFLOW['id'], 'text': PART2}],
    }
    monkeypatch.setattr(enrichment, 'get_item', lambda item_id: item)
    monkeypatch.setattr(enrichment, 'get_board', lambda board_id: {'id': board_id, 'columns': WITH_OVERFLOW})
    monkeypatch.setattr(enrichment, 'load_relation_taxonomies', lambda columns: {})
    monkeypatch.setattr(enrichment, 'classify_country', lambda address: 'DE')

    def research(prompt):
        seen['prompt'] = prompt
        return {'text': seen['answer'], 'searched': True, 'search_count': 1}

    def write_columns(board_id, item_id, values):
        seen['values'] = values
        return {'written': len(values), 'dropped': []}

    monkeypatch.setattr(enrichment, 'research', research)
    monkeypatch.setattr(enrichment, 'write_columns', write_columns)
    return seen


def test_the_research_gets_the_whole_name_name_2_included(run):
    run['answer'] = 'CORRECT_NAME: ANDREAS STIHL AG & Co. KG'
    enrichment.enrich_item('5106281544', '42')

    assert LONG in run['prompt']
    assert run['values'][NAME_ID] == 'ANDREAS STIHL AG & Co. KG'
    assert run['values'][OVERFLOW['id']] == ''


def test_nothing_researched_writes_neither_name_column(run):
    run['answer'] = 'CORRECT_NAME: Not found\nCITY: München'
    enrichment.enrich_item('5106281544', '42')

    assert NAME_ID not in run['values']
    assert OVERFLOW['id'] not in run['values']
