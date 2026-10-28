"""
The board_relation columns: Industry and Job Function.

Both link to items on a separate taxonomy board, and the board's mirrors read
Industry Score / Role Score / Department / Hauptbrachen through that link into
Initial Lead Score. Enrichment used to leave both blank, so those mirrors were
empty and every enriched lead scored on incomplete inputs.

taxonomy.json is a slice of the real boards, so the names here are spelled the
way the live taxonomy spells them - German, bracketed, and in four cases
duplicated with different scores behind each copy.

  pytest
"""
import json
import re
from pathlib import Path

from app.features.company_enrichment.lib.mapping import build_column_values
from app.features.company_enrichment.lib.parse import parse_enrichment
from app.features.company_enrichment.lib.prompt import build_prompt
from app.features.company_enrichment.lib.taxonomy import connected_board_id, match_taxonomy_item, taxonomy_choices

HERE = Path(__file__).parent
taxonomy = json.loads((HERE / 'taxonomy.json').read_text())
industries = taxonomy['industries']
job_functions = taxonomy['jobFunctions']

boards = json.loads((HERE / 'boards.json').read_text())['data']['boards']
warm = next(b for b in boards if b['id'] == '5100825258')
cold = next(b for b in boards if b['id'] == '5100463291')


def id_of(board, title):
    return next((c['id'] for c in board['columns'] if c['title'] == title), None)


def with_relation_settings(board, industry_settings):
    """
    boards.json predates `settings_str` in the board query, so the connected
    board ids are attached here. The cold board's Industry column really does
    carry only `boardIds` with no `boardId` key - that asymmetry is the point of
    the test below.
    """
    def attach(column):
        if column['title'] == 'Industry':
            return {**column, 'settings_str': json.dumps(industry_settings)}
        if column['title'] == 'Job Function':
            return {**column, 'settings_str': json.dumps({'boardIds': [int(taxonomy['jobFunctionBoardId'])]})}
        return column

    return {**board, 'columns': [attach(column) for column in board['columns']]}


def relations_for(board):
    """columnId -> taxonomy items, as enrichment.py assembles it before the write."""
    return {id_of(board, 'Industry'): industries, id_of(board, 'Job Function'): job_functions}


def answer(industry, job_function):
    return f"""
CORRECT_NAME: Muster Großhandel GmbH
CONTACT_NAME: Michael Dietzel
INDUSTRY: {industry}
JOB_FUNCTION: {job_function}
"""


def test_the_researched_industry_and_job_function_are_linked_by_item_id():
    fields = parse_enrichment(answer('Industrie & Produktion', 'Vertriebsleiter (CSO)'))
    result = build_column_values(warm['columns'], fields, relations_for(warm))

    assert result['values'][id_of(warm, 'Industry')] == {'item_ids': ['2820930311']}
    assert result['values'][id_of(warm, 'Job Function')] == {'item_ids': ['2872722273']}

    assert [f"{e['title']}={e['name']}" for e in result['linked']] == [
        'Industry=Industrie & Produktion',
        'Job Function=Vertriebsleiter (CSO)',
    ]


def test_both_boards_get_linked_though_the_columns_have_different_ids():
    fields = parse_enrichment(answer('Transport & Logistik', 'Geschäftsführung'))

    for board in [warm, cold]:
        values = build_column_values(board['columns'], fields, relations_for(board))['values']
        assert values[id_of(board, 'Industry')] == {'item_ids': ['2820930278']}
        assert values[id_of(board, 'Job Function')] == {'item_ids': ['2872725350']}


def test_a_name_the_taxonomy_does_not_have_is_never_invented_and_survives_in_comments():
    fields = parse_enrichment(answer('Software & SaaS', 'Chief Happiness Officer'))
    result = build_column_values(warm['columns'], fields, relations_for(warm))
    values = result['values']

    # Nothing written: a relation has no "N/A" to fall back on.
    assert id_of(warm, 'Industry') not in values
    assert id_of(warm, 'Job Function') not in values
    assert 'Industry' in result['skipped']
    assert 'Job Function' in result['skipped']

    # But the research is not lost.
    comments = values[id_of(warm, 'Comments')]['text']
    assert re.search(r'Industry \(no matching option\): Software & SaaS', comments)
    assert re.search(r'Job Function \(no matching option\): Chief Happiness Officer', comments)

    assert sorted(e['title'] for e in result['unmatched'] if e['title'] in ('Industry', 'Job Function')) == [
        'Industry',
        'Job Function',
    ]


def test_not_found_is_treated_as_no_answer_not_as_a_value_to_match():
    fields = parse_enrichment(answer('Not found', 'Not found'))
    result = build_column_values(warm['columns'], fields, relations_for(warm))

    assert id_of(warm, 'Industry') not in result['values']
    assert 'Industry' in result['skipped']
    # Nothing was researched, so there is nothing to report to a human either.
    assert [e for e in result['unmatched'] if e['title'] in ('Industry', 'Job Function')] == []


def test_with_no_taxonomy_loaded_the_columns_are_skipped_not_broken():
    fields = parse_enrichment(answer('Industrie & Produktion', 'Geschäftsführung'))
    result = build_column_values(warm['columns'], fields)

    assert id_of(warm, 'Industry') not in result['values']
    assert 'Industry' in result['skipped']
    # The rest of the write is untouched.
    assert result['values'][id_of(warm, 'Company / Customer Name')] == 'Muster Großhandel GmbH'


def test_a_model_that_drops_the_bracketed_detail_still_matches():
    m = match_taxonomy_item(industries, 'Großhandel')
    assert m['name'] == (
        'Großhandel (Industrie-; Arbeitsschutz-; Hygiene-; Auto-; Farb-; Bau-; Medizin- und Sanitärgroßhandel)'
    )
    assert match_taxonomy_item(job_functions, 'Finanzvorstand')['name'] == 'Finanzvorstand (CFO)'


def test_german_is_matched_through_und_umlauts_and_casing():
    assert match_taxonomy_item(industries, 'industrie und produktion')['name'] == 'Industrie & Produktion'
    assert match_taxonomy_item(industries, 'BANKEN & VERSICHERUNGEN')['name'] == 'Banken & Versicherungen'
    assert match_taxonomy_item(job_functions, 'geschaeftsfuehrung')['name'] == 'Geschäftsführung'


def test_a_duplicated_taxonomy_name_resolves_to_the_oldest_item_and_is_reported():
    """
    Four names exist twice on the Job Function board with different Role Scores
    behind them - "Geschäftsführer" is 13 on one and 10 on the other. An unstable
    tie-break would make the lead score depend on the order monday returned rows
    in, so the oldest item wins and the collision is reported.
    """
    m = match_taxonomy_item(job_functions, 'Geschäftsführer')

    assert m['id'] == '2872722656'
    assert m['ambiguous'] == ['2872722656', '2872726857']
    assert match_taxonomy_item(job_functions, 'Geschäftsführer')['id'] == m['id'], 'must be stable'


def test_the_collision_reaches_the_caller_so_the_run_log_can_name_it():
    fields = parse_enrichment(answer('Handel & Vertrieb', 'Scrum Master'))
    ambiguous = build_column_values(warm['columns'], fields, relations_for(warm))['ambiguous']

    assert len(ambiguous) == 1
    assert ambiguous[0]['title'] == 'Job Function'
    assert len(ambiguous[0]['ids']) == 2


def test_a_substring_is_not_enough_to_link_a_lead_to_an_industry():
    """
    "Handel" sits inside Großhandel, Einzelhandel and Onlinehandel. Picking one of
    those would write a score nobody chose, and silently - a wrong link is worse
    than no link, because no link is logged and kept in Comments.
    """
    # Inside "Chemie- & Pharmaindustrie", but not a prefix of it.
    assert match_taxonomy_item(industries, 'Pharma') is None
    assert match_taxonomy_item(industries, 'Logistik') is None

    # A prefix, but mid-word: four characters must not pick an Industry Score.
    assert match_taxonomy_item(industries, 'Auto') is None
    assert match_taxonomy_item(industries, 'Groß') is None

    # A prefix ending on a word boundary is still allowed - and flagged when it
    # lands on more than one row.
    assert len(match_taxonomy_item(industries, 'Handel')['ambiguous']) > 0


def test_every_real_taxonomy_name_resolves_to_itself():
    for items in [industries, job_functions]:
        for item in items:
            m = match_taxonomy_item(items, item['name'])
            assert m, f"no match for {item['name']}"
            assert m['name'].lower() == item['name'].lower()


def test_an_empty_or_absent_taxonomy_matches_nothing_rather_than_throwing():
    assert match_taxonomy_item([], 'Industrie & Produktion') is None
    assert match_taxonomy_item(None, 'Industrie & Produktion') is None
    assert match_taxonomy_item(industries, '') is None


def test_the_connected_board_is_read_from_board_ids_not_board_id():
    """The cold board's Industry column carries boardIds with no boardId key."""
    assert connected_board_id({'settings_str': '{"boardIds":[5094116229]}'}) == '5094116229'
    assert connected_board_id({'settings_str': '{"boardIds":[5094116229],"boardId":5094116229}'}) == '5094116229'
    # Nothing configured, or unparsable - no board, and no crash.
    assert connected_board_id({'settings_str': '{}'}) == ''
    assert connected_board_id({'settings_str': 'not json'}) == ''
    assert connected_board_id(None) == ''


def test_the_choices_handed_to_the_model_come_from_the_board_the_column_points_at():
    board = with_relation_settings(warm, {'boardIds': [int(taxonomy['industryBoardId'])]})
    relations = relations_for(board)

    chosen = taxonomy_choices(relations, board['columns'], 'Industry')
    assert len(chosen) == len(industries)
    assert 'Industrie & Produktion' in chosen

    # De-duplicated, so the model never sees the collision.
    roles = taxonomy_choices(relations, board['columns'], 'Job Function')
    assert len(roles) == len(set(roles))
    assert len(roles) < len(job_functions), 'the duplicate names should collapse'

    assert taxonomy_choices(relations, board['columns'], 'No Such Column') == []


def test_the_prompt_asks_for_the_two_fields_quoting_the_list_verbatim():
    prompt = build_prompt('Muster GmbH', 'Musterstr. 1, 10115 Berlin', {
        'industries': [i['name'] for i in industries],
        'job_functions': [i['name'] for i in job_functions],
    })

    assert re.search(r'^INDUSTRY - choose exactly one', prompt, re.MULTILINE)
    assert re.search(r'^JOB_FUNCTION - the role of the person named in CONTACT_NAME', prompt, re.MULTILINE)
    assert '- Industrie & Produktion' in prompt
    assert (
        '- Großhandel (Industrie-; Arbeitsschutz-; Hygiene-; Auto-; Farb-; Bau-; Medizin- und Sanitärgroßhandel)'
        in prompt
    ), 'the bracketed name must be quoted in full, or the model cannot echo it back'
    assert re.search(r'Do NOT translate, abbreviate, reword or invent a value', prompt)

    # The master prompt is still intact ahead of the new section.
    assert 'CRITICAL INSTRUCTION: You MUST perform AT LEAST 15-20 web searches' in prompt
    assert prompt.index('EXTRA FIELDS') < prompt.index('CLASSIFICATION FIELDS')


def test_with_no_taxonomy_the_prompt_does_not_invite_the_model_to_make_one_up():
    prompt = build_prompt('Muster GmbH', 'Musterstr. 1', {})

    assert 'CLASSIFICATION FIELDS' not in prompt
    assert 'INDUSTRY -' not in prompt
    # Unchanged from the build that had no relation support at all.
    assert prompt == build_prompt('Muster GmbH', 'Musterstr. 1')
