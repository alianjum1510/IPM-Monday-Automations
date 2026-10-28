"""
Runs the parser + mapper against the real column schemas of both boards.

  pytest
"""
import json
import re
from pathlib import Path

from app.features.company_enrichment.lib.mapping import (
    LIFECYCLE_STAGE_ENRICHED,
    LIFECYCLE_STAGE_TITLE,
    NA_TEXT,
    build_column_values,
    may_advance_stage,
    option_choices,
)
from app.features.company_enrichment.lib.parse import parse_enrichment
from app.features.company_enrichment.lib.prompt import build_prompt

boards = json.loads((Path(__file__).parent / 'boards.json').read_text())['data']['boards']
warm = next(b for b in boards if b['id'] == '5100825258')
cold = next(b for b in boards if b['id'] == '5100463291')


def title_of(board, column_id):
    return next((c['title'] for c in board['columns'] if c['id'] == column_id), None)


def id_of(board, title):
    return next((c['id'] for c in board['columns'] if c['title'] == title), None)


def with_settings(board, title, settings):
    return {
        **board,
        'columns': [
            {**column, 'settings_str': json.dumps(settings)} if column['title'] == title else column
            for column in board['columns']
        ],
    }


def with_dropdown_labels(board, title, names):
    """The dropdown shape of settings_str, which differs from status."""
    return with_settings(board, title, {'labels': [{'id': i + 1, 'name': name} for i, name in enumerate(names)]})


FULL_ANSWER = """
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
"""


def test_the_email_lands_in_company_email_never_in_email():
    for board in [warm, cold]:
        values = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))['values']

        assert values[id_of(board, 'Company Email')] == {'email': 'info@stihl.de', 'text': 'info@stihl.de'}

        assert id_of(board, 'Email') not in values, 'lead_email must be left alone'
        assert 'lead_email' not in values


def test_typed_columns_get_monday_shaped_values():
    board = with_dropdown_labels(warm, 'Phone Type', ['Landline', 'Mobile', 'VoIP'])
    values = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))['values']

    assert values[id_of(warm, 'Company / Customer Name')] == 'ANDREAS STIHL AG & Co. KG'
    assert values[id_of(warm, 'Registration Number')] == 'HRA 260269'
    assert values[id_of(warm, 'Postal Code')] == '71336'
    assert values[id_of(warm, 'Country')] == {'countryCode': 'DE', 'countryName': 'Germany'}
    assert values[id_of(warm, 'Main Phone')] == {'phone': '+497151260', 'countryShortName': 'DE'}
    assert values[id_of(warm, 'Website')] == {'url': 'https://www.stihl.de', 'text': 'www.stihl.de'}
    assert values[id_of(warm, 'Company Size')] == '20000', 'thousands separator stripped'
    assert values[id_of(warm, 'Phone Type')] == {'ids': [1]}, 'by id, never a label string'


def test_the_vat_number_and_confidences_survive_in_comments():
    values = build_column_values(warm['columns'], parse_enrichment(FULL_ANSWER))['values']
    comments = values[id_of(warm, 'Comments')]['text']

    assert re.search(r'VAT \(USt-IdNr\): DE146214838', comments)
    assert re.search(r'HRB confidence: HIGH \(handelsregister\.de\)', comments)
    assert re.search(r'Registry court: Amtsgericht Stuttgart', comments)
    assert re.search(r'21 searches performed', comments)


def test_empty_text_columns_and_dropdowns_that_offer_it_are_filled_with_na():
    sparse = parse_enrichment("""
CORRECT_NAME: Kleine Firma GmbH
REGISTRATION_NUMBER: Not found after extensive search
CITY: Berlin
COUNTRY: Not found
COMPANY_EMAIL: Not found
MAIN_PHONE: Not found
COMPANY_SIZE: Not found
OWNERSHIP_TYPE: Not found
""")

    board = with_dropdown_labels(warm, 'Ownership Type', ['Private', 'Public', NA_TEXT])
    result = build_column_values(board['columns'], sparse)
    values, filled, skipped = result['values'], result['filled'], result['skipped']

    assert values[id_of(warm, 'Registration Number')] == NA_TEXT
    assert values[id_of(warm, 'Address Line 1')] == NA_TEXT
    assert values[id_of(warm, 'District')] == NA_TEXT
    assert values[id_of(warm, 'Ownership Type')] == {'ids': [3]}, 'the existing N/A option'
    assert values[id_of(warm, 'City')] == 'Berlin', 'a real value is not overwritten with N/A'

    # The columns that sat blank in the board screenshot.
    assert values[id_of(warm, 'LinkedIn Profile')] == {'url': NA_TEXT, 'text': NA_TEXT}
    assert values[id_of(warm, 'Website')] == {'url': NA_TEXT, 'text': NA_TEXT}
    assert values[id_of(warm, 'Mobile Number')] == {'phone': NA_TEXT, 'countryShortName': ''}
    assert values[id_of(warm, 'Company Email')] == {'email': NA_TEXT, 'text': NA_TEXT}

    for title in ['LinkedIn Profile', 'Website', 'Mobile Number', 'Company Email']:
        assert title in filled, f'{title} should be N/A-filled'

    # Number, date and country columns have nowhere to keep the string "N/A".
    for title in ['Company Size', 'Country']:
        assert id_of(warm, title) not in values, f'{title} must stay empty'
        assert title in skipped, f'{title} should be reported as skipped'
    assert 'Registration Number' in filled


def test_placeholder_echoes_and_not_found_phrasings_normalise_to_empty():
    fields = parse_enrichment("""
CORRECT_NAME: [legal name]
REGISTRATION_NUMBER: Not found after extensive search
UID_NUMBER: N/A
HANDELSREGISTER_VERIFIED: No
CITY: Hamburg
""")

    assert fields['CORRECT_NAME'] == ''
    assert fields['REGISTRATION_NUMBER'] == ''
    assert fields['UID_NUMBER'] == ''
    assert fields['HANDELSREGISTER_VERIFIED'] == 'No', 'a real "No" answer is kept'
    assert fields['CITY'] == 'Hamburg'


def test_commentary_after_the_registration_number_is_dropped():
    cases = {
        'KRS 0000657029 — no German HRB/HRA found after extensive search': 'KRS 0000657029',
        'HRB 12345 B - Amtsgericht Charlottenburg': 'HRB 12345 B',
        'HRA 260269 (verified on handelsregister)': 'HRA 260269',
        'HRB 98765; historical HRB 1111 in NOTES': 'HRB 98765',
        'No German HRB/HRA found': '',
        'Not found — KRS 0000657029 (Polish register)': 'KRS 0000657029',
        'No German HRB/HRA found; Polish KRS 0000657029': 'KRS 0000657029',
        'Not found in Handelsregister, KRS: 0000657029': 'KRS: 0000657029',
        'Not found after 20 searches': '',
        'N/A': '',
        '01234567': '01234567',
    }
    for given, expected in cases.items():
        assert parse_enrichment(f'REGISTRATION_NUMBER: {given}')['REGISTRATION_NUMBER'] == expected, given


def test_multi_line_notes_are_kept_whole():
    fields = parse_enrichment("""
NOTES: First line of notes.
Second line continues here.
CITY: Köln
""")

    assert fields['NOTES'] == 'First line of notes. Second line continues here.'
    assert fields['CITY'] == 'Köln'


def with_stage_labels(board, labels):
    """
    boards.json predates `settings_str` in the board query, so the label lists
    are built here. The warm list mirrors the board as it stands: the capital-A
    label the board has always had, plus the lowercase duplicate an earlier
    build's `create_labels_if_missing` write invented at index 106.
    """
    return with_settings(board, LIFECYCLE_STAGE_TITLE, {'labels': labels})


WARM_STAGE_LABELS = {
    '0': 'Inbound',
    '1': 'Data Authentication Required',
    '2': 'Discovery Booked',
    '3': 'Data Complete',
    '4': 'Disqualified',
    '5': 'Nurture List',
    '6': 'Short Route- Discovery',
    '106': 'Data authentication required',
}


def test_the_stage_reuses_the_board_label_that_differs_only_in_casing():
    board = with_stage_labels(warm, WARM_STAGE_LABELS)
    values = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))['values']

    # Index 1, not 106: the board's own label, never the duplicate.
    assert values[id_of(board, LIFECYCLE_STAGE_TITLE)] == {'index': 1}


def test_the_stage_is_written_by_index_so_no_label_can_ever_be_created():
    board = with_stage_labels(warm, WARM_STAGE_LABELS)
    values = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))['values']
    written = values[id_of(board, LIFECYCLE_STAGE_TITLE)]

    assert 'label' not in written, 'a label string would let monday invent one'
    assert isinstance(written['index'], int)


def test_a_renamed_stage_label_is_still_found_by_its_prefix():
    board = with_stage_labels(warm, {'0': 'Inbound', '4': 'Data Authentication Pending'})
    values = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))['values']

    assert values[id_of(board, LIFECYCLE_STAGE_TITLE)] == {'index': 4}


def test_an_unrecognisable_stage_column_is_left_alone_rather_than_guessed_at():
    board = with_stage_labels(warm, {'0': 'Inbound', '1': 'Discovery Booked'})
    result = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))

    assert id_of(board, LIFECYCLE_STAGE_TITLE) not in result['values']
    assert LIFECYCLE_STAGE_TITLE in result['skipped']


def test_a_stage_column_with_no_settings_at_all_cannot_break_the_write():
    # boards.json as-is: no settings_str on any column.
    result = build_column_values(warm['columns'], parse_enrichment(FULL_ANSWER))

    assert id_of(warm, LIFECYCLE_STAGE_TITLE) not in result['values']
    assert LIFECYCLE_STAGE_TITLE in result['skipped']
    assert len(result['values']) >= 20, 'the rest of the write is unaffected'


# The stage guard. A run takes minutes, so the lead can move while it is in
# flight - these are the stages the finished run may and may not write over.

def test_a_lead_still_waiting_on_enrichment_has_its_stage_advanced():
    assert may_advance_stage(''), 'no stage at all'
    assert may_advance_stage('Inbound')
    assert may_advance_stage('Data Authentication Required'), 'a re-run'
    assert may_advance_stage('data authentication required'), 'the casing duplicate'
    assert may_advance_stage('Data Authentication Pending'), 'renamed, still the same stage'


def test_a_lead_that_moved_on_during_the_run_keeps_its_stage():
    # The reported bug: booked a call mid-run, finished run pulled it back.
    assert may_advance_stage('Discovery Booked') is False

    for stage in ['Data Complete', 'Disqualified', 'Nurture List', 'Short Route- Discovery']:
        assert may_advance_stage(stage) is False, f'{stage} must not be overwritten'


def test_a_downstream_stage_added_to_the_board_later_is_protected_by_default():
    # An allowlist, so a label nobody told this app about is held, not overwritten.
    assert may_advance_stage('Contract Sent') is False


def test_a_board_whose_leads_arrive_on_another_stage_can_say_so():
    assert may_advance_stage('New Lead', ['New Lead', LIFECYCLE_STAGE_ENRICHED])
    assert may_advance_stage('Inbound', ['New Lead']) is False, 'the override replaces the default'


def test_the_stage_moves_for_a_sparse_answer_too():
    board = with_stage_labels(cold, WARM_STAGE_LABELS)
    values = build_column_values(board['columns'], parse_enrichment('CORRECT_NAME: Kleine Firma GmbH'))['values']

    assert values[id_of(board, LIFECYCLE_STAGE_TITLE)] == {'index': 1}


DIALLING_CODES = ['+1', '+20', '+212', '+213', '+216', '+43', '+49', '+92']


def option_id(code):
    return DIALLING_CODES.index(code) + 1


# Estimated Annual Revenue as it stands on the warm board.
REVENUE_BANDS = ['< 1M EUR', '1M-10M EUR', '10M-50M EUR', '50M-100M EUR', '100M-500M EUR', '500M+ EUR']


def test_web_search_citations_are_stripped_from_the_data_fields():
    fields = parse_enrichment("""
CONTACT_NAME: Michael Dietzel; Boris Sobot — Vorstand ([svg-sued.de](https://www.svg-sued.de/impressum?utm_source=openai))
HOMEPAGE: [www.svg-sued.de](https://www.svg-sued.de?utm_source=openai)
CORRECT_NAME: SVG Süd GmbH ([handelsregister.de](https://www.handelsregister.de))
""")

    assert fields['CONTACT_NAME'] == 'Michael Dietzel; Boris Sobot — Vorstand'
    assert fields['HOMEPAGE'] == 'www.svg-sued.de'
    assert fields['CORRECT_NAME'] == 'SVG Süd GmbH'


def test_the_verification_trail_keeps_its_sources():
    fields = parse_enrichment("""
HRB_CONFIDENCE: HIGH (handelsregister.de)
COMPANY_STATUS: Active (companyhouse.de)
VAT_CONFIDENCE: HIGH (company Impressum page)
VERIFICATION_SOURCE: https://www.stihl.de/impressum?utm_source=openai
""")

    assert fields['HRB_CONFIDENCE'] == 'HIGH (handelsregister.de)'
    assert fields['COMPANY_STATUS'] == 'Active (companyhouse.de)'
    assert fields['VAT_CONFIDENCE'] == 'HIGH (company Impressum page)'
    assert fields['VERIFICATION_SOURCE'] == 'https://www.stihl.de/impressum', 'utm stripped'


def test_country_code_gets_the_dialling_code_taken_from_the_phone_number():
    board = with_dropdown_labels(warm, 'Country Code', DIALLING_CODES)
    values = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))['values']

    assert values[id_of(board, 'Country Code')] == {'ids': [option_id('+49')]}


def test_a_longer_dialling_code_is_not_swallowed_by_a_shorter_one():
    board = with_dropdown_labels(warm, 'Country Code', DIALLING_CODES)
    fields = parse_enrichment('COUNTRY: Morocco\nCOUNTRY_CODE: MA\nMAIN_PHONE: +212 522 123456')

    values = build_column_values(board['columns'], fields)['values']
    assert values[id_of(board, 'Country Code')] == {'ids': [option_id('+212')]}, 'not +21 or +2'


def test_with_no_phone_at_all_the_dialling_code_comes_from_the_iso_code():
    board = with_dropdown_labels(warm, 'Country Code', DIALLING_CODES)
    values = build_column_values(board['columns'], parse_enrichment('COUNTRY_CODE: DE'))['values']

    assert values[id_of(board, 'Country Code')] == {'ids': [option_id('+49')]}


def test_the_iso_code_still_goes_to_the_country_column():
    board = with_dropdown_labels(warm, 'Country Code', DIALLING_CODES)
    values = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))['values']

    assert values[id_of(board, 'Country')] == {'countryCode': 'DE', 'countryName': 'Germany'}


def test_a_dropdown_option_is_never_invented_and_the_value_survives_in_comments():
    board = with_dropdown_labels(with_stage_labels(warm, WARM_STAGE_LABELS), 'Company Structure', ['GmbH', 'AG'])
    result = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))

    # "AG & Co. KG" is not on the list, and neither is N/A - the cell is left alone.
    assert id_of(board, 'Company Structure') not in result['values']
    assert 'Company Structure' in result['skipped']
    assert 'Company Structure' not in result['filled'], 'no N/A option to fall back on'
    # The fixture's other dropdowns have no options either, so they report too.
    assert [e for e in result['unmatched'] if e['title'] == 'Company Structure'] == [
        {'title': 'Company Structure', 'value': 'AG & Co. KG'},
    ]
    assert re.search(
        r'Company Structure \(no matching option\): AG & Co\. KG',
        result['values'][id_of(board, 'Comments')]['text'],
    )


def test_a_revenue_band_that_is_not_an_option_goes_to_the_nearest_band():
    board = with_dropdown_labels(warm, 'Estimated Annual Revenue', ['0-1M EUR', '1M-10M EUR'])
    result = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))

    # "1B+ EUR" is far above both bands; 1M-10M is the nearest, never a new option.
    assert result['values'][id_of(board, 'Estimated Annual Revenue')] == {'ids': [2]}
    assert not any(e['title'] == 'Estimated Annual Revenue' for e in result['unmatched'])
    assert re.search(
        r'Estimated Annual Revenue figure: 1B\+ EUR - 1B EUR -> nearest option 1M-10M EUR',
        result['values'][id_of(board, 'Comments')]['text'],
    )


def test_an_unmatched_dropdown_falls_back_to_na_only_when_na_is_one_of_its_options():
    board = with_dropdown_labels(warm, 'Company Structure', ['GmbH', 'AG', NA_TEXT])
    result = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))

    assert result['values'][id_of(board, 'Company Structure')] == {'ids': [3]}
    assert 'Company Structure' in result['filled']


def test_the_boards_own_revenue_bands_are_matched_symbols_and_all():
    board = with_dropdown_labels(warm, 'Estimated Annual Revenue', REVENUE_BANDS)
    column_id = id_of(board, 'Estimated Annual Revenue')

    for given, band in [('10M-50M EUR', 3), ('< 1M EUR', 1), ('500M+ EUR', 6), ('"1M-10M EUR"', 2)]:
        values = build_column_values(board['columns'], parse_enrichment(f'ESTIMATED_ANNUAL_REVENUE: {given}'))['values']
        assert values[column_id] == {'ids': [band]}, given


def test_a_dropdown_with_no_options_of_its_own_is_left_empty_never_free_text():
    # boards.json has no settings_str, so no dropdown has a readable list.
    result = build_column_values(warm['columns'], parse_enrichment(FULL_ANSWER))

    for title in ['Phone Type', 'Estimated Annual Revenue', 'Company Structure', 'Ownership Type']:
        assert id_of(warm, title) not in result['values'], f'{title} must not be written'
    assert any(e['title'] == 'Phone Type' and e['value'] == 'Landline' for e in result['unmatched'])


def test_a_deactivated_dropdown_option_is_not_written():
    board = with_settings(warm, 'Phone Type', {
        'labels': [{'id': 1, 'name': 'Landline'}, {'id': 2, 'name': 'Mobile'}],
        'deactivated_labels': [1],
    })
    values = build_column_values(board['columns'], parse_enrichment(FULL_ANSWER))['values']

    assert id_of(board, 'Phone Type') not in values
    assert option_choices(board['columns'])['PHONE_TYPE'] == ['Mobile']


def test_the_prompt_offers_the_dropdowns_own_options_and_nothing_else():
    board = with_dropdown_labels(
        with_dropdown_labels(warm, 'Estimated Annual Revenue', [*REVENUE_BANDS, NA_TEXT]),
        'Country Code',
        DIALLING_CODES,
    )
    options = option_choices(board['columns'])

    assert options['ESTIMATED_ANNUAL_REVENUE'] == REVENUE_BANDS, 'N/A comes from "Not found", not a choice'
    assert 'COUNTRY_CODE' not in options, 'derived from the phone number, never asked for'

    prompt = build_prompt('Muster GmbH', 'Badstraße 115, 71336 Waiblingen', {'options': options})
    assert re.search(r'ESTIMATED_ANNUAL_REVENUE: \[choose ONE of: "< 1M EUR" \| "1M-10M EUR"', prompt)
    assert re.search(r'DROPDOWN FIELDS: ESTIMATED_ANNUAL_REVENUE fill fixed dropdowns', prompt)
    assert not re.search(r'revenue band, e\.g\.', prompt)

    # A board whose options could not be read keeps the old hints.
    plain = build_prompt('Muster GmbH', 'Badstraße 115, 71336 Waiblingen')
    assert re.search(r'ESTIMATED_ANNUAL_REVENUE: \[revenue band, e\.g\. "1M-10M EUR"\]', plain)
    assert not re.search(r'DROPDOWN FIELDS', plain)


def test_every_planned_column_exists_on_at_least_one_board():
    values = build_column_values(cold['columns'], parse_enrichment(FULL_ANSWER))['values']
    written = [title_of(cold, column_id) for column_id in values]

    assert 'Company Email' in written
    assert len(written) >= 20, f'expected a full write, got {len(written)} columns'


def test_notes_the_model_attaches_to_the_company_name_are_cut_off():
    cases = {
        'Muster GmbH (verified on handelsregister.de)': 'Muster GmbH',
        'Muster GmbH — legal name as registered': 'Muster GmbH',
        'Muster GmbH; formerly Alt Muster GmbH': 'Muster GmbH',
        'Muster GmbH, formerly Alt Muster GmbH': 'Muster GmbH',
        'Muster GmbH verified via Impressum': 'Muster GmbH',
        'Muster GmbH & Co. KG (HIGH confidence)': 'Muster GmbH & Co. KG',
        'Legal name: Muster GmbH': 'Muster GmbH',
    }
    for given, expected in cases.items():
        assert parse_enrichment(f'CORRECT_NAME: {given}')['CORRECT_NAME'] == expected, given


def test_a_real_company_name_is_left_exactly_as_it_is():
    for name in [
        'ANDREAS STIHL AG & Co. KG',
        'Muster (Deutschland) GmbH',
        'Rhein - Main Bau GmbH',
        'Müller, Meier & Partner mbB',
        'The Coca-Cola Company GmbH',
        'Dr. Oetker Nahrungsmittel KG',
    ]:
        assert parse_enrichment(f'CORRECT_NAME: {name}')['CORRECT_NAME'] == name, name


def test_notes_the_model_attaches_to_the_address_are_cut_off():
    cases = {
        'CORRECT_ADDRESS: Badstraße 115, 71336 Waiblingen, Deutschland (Hauptsitz)':
            'Badstraße 115, 71336 Waiblingen, Deutschland',
        'CORRECT_ADDRESS: Badstraße 115, 71336 Waiblingen — as listed on the Impressum':
            'Badstraße 115, 71336 Waiblingen',
        'CORRECT_ADDRESS: Badstraße 115, 71336 Waiblingen, verified via handelsregister.de':
            'Badstraße 115, 71336 Waiblingen',
        'CORRECT_ADDRESS: Badstraße 115, 71336 Waiblingen. The company moved here in 2021.':
            'Badstraße 115, 71336 Waiblingen',
        'ADDRESS_LINE_1: Badstraße 115; formerly Hauptstraße 3': 'Badstraße 115',
        'CITY: Waiblingen (Rems-Murr-Kreis)': 'Waiblingen',
        'POSTAL_CODE: 71336 (confirmed)': '71336',
        'ADDRESS_LINE_1: Musterweg 1 - 3': 'Musterweg 1 - 3',
        'ADDRESS_LINE_2: c/o Muster GmbH': 'c/o Muster GmbH',
        'CITY: Am See': 'Am See',
    }
    for given, expected in cases.items():
        key = given.split(':')[0]
        assert parse_enrichment(given)[key] == expected, given


def test_an_address_that_is_still_prose_after_cleaning_is_not_written_at_all():
    fields = parse_enrichment('ADDRESS_LINE_1: Probably Badstraße 115 but this is unverified')
    assert fields['ADDRESS_LINE_1'] == ''

    values = build_column_values(warm['columns'], fields)['values']
    assert values[id_of(warm, 'Address Line 1')] == NA_TEXT


def test_a_note_on_the_line_after_the_address_never_reaches_the_cell():
    fields = parse_enrichment("""
CORRECT_ADDRESS: Badstraße 115, 71336 Waiblingen
Note: the old address on LinkedIn is outdated.
CITY: Waiblingen
""")
    assert fields['CORRECT_ADDRESS'] == 'Badstraße 115, 71336 Waiblingen'
    assert fields['CITY'] == 'Waiblingen'


def test_removed_notes_are_kept_in_comments_and_named_in_the_result():
    given = FULL_ANSWER.replace(
        'CORRECT_NAME: ANDREAS STIHL AG & Co. KG',
        'CORRECT_NAME: ANDREAS STIHL AG & Co. KG (verified on handelsregister.de)',
    )
    result = build_column_values(warm['columns'], parse_enrichment(given))

    assert result['values'][id_of(warm, 'Company / Customer Name')] == 'ANDREAS STIHL AG & Co. KG'
    assert re.search(
        r'Company / Customer Name \(note removed\): verified on handelsregister\.de',
        result['values'][id_of(warm, 'Comments')]['text'],
    )
    assert result['cleaned'] == ['Company / Customer Name']


def test_a_clean_answer_removes_nothing():
    result = build_column_values(warm['columns'], parse_enrichment(FULL_ANSWER))
    assert result['cleaned'] == []
    assert result['values'][id_of(warm, 'Full Address')] == 'Badstraße 115, 71336 Waiblingen, Deutschland'
    assert not re.search(r'note removed', result['values'][id_of(warm, 'Comments')]['text'])


def test_the_search_is_scoped_to_the_country_the_user_entered():
    with_country = build_prompt('Muster GmbH', 'Ringstraße 1, 1010 Wien, Austria', {}, 'Austria')
    assert re.search(r'Country: Austria\n', with_country)
    assert re.search(r'Restrict every search to that country', with_country)

    without_country = build_prompt('Muster GmbH', 'Badstraße 115, 71336 Waiblingen')
    assert re.search(r'Country: not identified - determine it from the address above', without_country)
