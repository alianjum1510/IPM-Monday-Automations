"""
The country is classified from the user's input before the research runs.

  pytest
"""
from app.features.company_enrichment.lib.country import country_code, country_from_input


def code_of(column, address):
    found = country_from_input(column, address)
    return found['code'] if found else None


def test_the_country_column_decides_first_in_any_language_or_as_a_code():
    assert code_of('Germany', 'Ringstraße 1, 1010 Wien, Austria') == 'DE'
    assert code_of('Österreich', '') == 'AT'
    assert code_of('CH', '') == 'CH'
    assert country_from_input('Germany', '')['source'] == 'Country column'


def test_a_country_name_in_the_address_classifies_the_lead():
    cases = {
        'Badstraße 115, 71336 Waiblingen, Deutschland': 'DE',
        'Ringstraße 1, 1010 Wien, Österreich': 'AT',
        'Ringstraße 1, 1010 Wien Österreich': 'AT',
        'Bahnhofstrasse 1, 8001 Zürich, Schweiz': 'CH',
        'Damrak 1, 1012 Amsterdam, Nederland': 'NL',
        'Rue de Rivoli 1, 75001 Paris, France': 'FR',
        'ul. Marszałkowska 1, 00-001 Warszawa, Polska': 'PL',
        '1 Main St, Springfield, IL 62701, USA': 'US',
        'Main Street 1, Dublin, Ireland': 'IE',
    }
    for address, code in cases.items():
        assert code_of('', address) == code, address


def test_a_postal_prefix_classifies_the_lead():
    assert code_of('', 'Badstraße 115, D-71336 Waiblingen') == 'DE'
    assert code_of('', 'Ringstraße 1, A-1010 Wien') == 'AT'
    assert code_of('', 'Bahnhofstrasse 1, CH-8001 Zürich') == 'CH'
    assert country_from_input('', 'Ringstraße 1, A-1010 Wien')['source'] == 'postal prefix in address'


def test_a_country_word_inside_the_street_does_not_classify_the_lead():
    assert code_of('', 'Schweizer Straße 3, 60594 Frankfurt') is None
    assert code_of('', 'Frankreichstraße 2, 10115 Berlin') is None


def test_an_address_with_only_a_city_is_left_for_the_model_to_place():
    assert code_of('', 'Badstraße 115, 71336 Waiblingen') is None
    assert code_of('', '') is None


def test_the_models_one_word_answer_is_validated_as_a_real_country_code():
    assert country_code('AT') == 'AT'
    assert country_code('UNKNOWN') == ''
    assert country_code('ZZ') == ''
    assert country_code('') == ''
