import datetime

import pytest

from app.features.vendor_search import mapping, matching, settings

from .conftest import vendor


# ---- matching ------------------------------------------------------------------------------

@pytest.mark.parametrize('a, b, same', [
    ('iPhone', 'iphone', True),
    ('iPhone', ' iPhone ', True),
    ('iPhone', 'IPHONE', True),
    ('Kühlschrank', 'kuehlschrank', False),
    ('Kühlschrank', 'kuhlschrank', True),
    ('iPhone', 'iPhone 15', False),
    ('Euro pallets', 'europallets', True),
    ('Euro pallets', 'Euro-Pallets', True),
    ('Euro pallets', 'eurppallets', False),  # a typo: left to the AI's same-product check
    ('', '', False),
])
def test_same_product(a, b, same):
    assert matching.same_product(a, b) is same


@pytest.mark.parametrize('name, key', [
    ('Tech World GmbH', 'tech world'),
    ('Tech-World GmbH & Co. KG', 'tech world'),
    ('TECH WORLD AG', 'tech world'),
    ('Müller Handels UG (haftungsbeschränkt)', 'muller handels'),
    ('Schmidt e.K.', 'schmidt'),
])
def test_company_key(name, key):
    assert matching.company_key(name) == key


@pytest.mark.parametrize('url, domain', [
    ('https://www.Tech-World.de/shop?x=1', 'tech-world.de'),
    ('tech-world.de', 'tech-world.de'),
    ('http://tech-world.de:8080/', 'tech-world.de'),
    ('', ''),
    ('not a url', ''),
])
def test_domain_of(url, domain):
    assert matching.domain_of(url) == domain


def test_existing_repeats_by_name_or_website():
    known = matching.Existing([{'name': 'Tech World', 'website': 'https://www.tech-world.de'}])
    assert known.repeats('Tech World GmbH')
    assert known.repeats('Other Name', 'tech-world.de/impressum')
    assert not known.repeats('Other Name', 'https://other.de')
    known.add('Other Name', 'https://other.de')
    assert known.repeats('OTHER NAME')
    assert known.repeats(['Unknown', 'Other Name'])


def test_a_row_named_after_its_product_is_known_by_its_legal_name_only():
    known = matching.Existing([{'name': 'Nitrile gloves', 'products': ['Nitrile gloves'],
                                'legal_name': 'PAUL HARTMANN AG', 'website': ''}])
    assert known.repeats('Paul Hartmann')
    assert not known.repeats('Nitrile Gloves')


def test_germany_check_passes_a_verified_german_vendor():
    assert matching.germany_problem(vendor('A')) is None


@pytest.mark.parametrize('overrides, problem', [
    ({'based_in_germany': False}, 'not confirmed as based in Germany'),
    ({'based_in_germany': 'yes'}, 'not confirmed as based in Germany'),
    ({'country_code': 'AT'}, 'country is AT'),
    ({'complete_address': ''}, 'no full address'),
    ({'postal_code': '1010', 'complete_address': 'Ring 1, 1010 Wien'}, 'no German postal code'),
    ({'complete_address': 'Hauptstraße 1, 12345 Musterstadt, Österreich'}, 'address is outside Germany'),
    ({'address_source_url': 'impressum page'}, 'address has no source'),
])
def test_germany_check_rejects(overrides, problem):
    assert matching.germany_problem(vendor('A', **overrides)) == problem


@pytest.mark.parametrize('overrides', [{'sells_exact_product': False}, {'product_evidence_url': None}])
def test_product_check_rejects(overrides):
    assert matching.product_problem(vendor('A', **overrides))


@pytest.mark.parametrize('candidate, ok', [
    ({'name': 'A', 'country': 'Germany', 'postal_code': '80331'}, True),
    ({'name': 'A', 'country': 'Deutschland'}, True),
    ({'name': 'A'}, True),
    ({'name': 'A', 'country': 'Austria'}, False),
    ({'name': 'A', 'postal_code': '1010'}, False),
    ({'name': ''}, False),
])
def test_candidate_check(candidate, ok):
    assert (matching.candidate_problem(candidate) is None) is ok


# ---- mapping -------------------------------------------------------------------------------

@pytest.mark.parametrize('value, expected', [
    ('info@firma.de', 'info@firma.de'),
    ('mailto:info@firma.de', 'info@firma.de'),
    ('N/A', ''),
    ('Not found', ''),
    ('info(at)firma.de', ''),
    ('<info@firma.de>', ''),
    (None, ''),
])
def test_email(value, expected):
    assert mapping.email(value) == expected


@pytest.mark.parametrize('value, expected', [
    ('+49 89 1234567', '+49891234567'),
    ('089 / 123 45 67', '+49891234567'),
    ('+49 (0) 89 1234567', '+49891234567'),
    ('0049 89 1234567', '+49891234567'),
    ('+43 1 234567', ''),
    ('123', ''),
    ('null', ''),
])
def test_phone(value, expected):
    assert mapping.phone(value) == expected


@pytest.mark.parametrize('value, expected', [
    (250, 250), ('250', 250), ('1.200', 1200), ('1,200', 1200), ('ca. 250', 250),
    ('51-200', 126), ('51 – 200', 126), ('50 bis 200', 125), ('11-50', 30), ('1.001-5.000 Mitarbeiter', 3000),
    ('200-51', None), ('unknown', None), (0, None), (True, None),
])
def test_employees_a_number_or_the_middle_of_a_range(value, expected):
    assert mapping.employees(value) == expected


def test_a_range_is_written_as_its_middle_value_into_company_size():
    values = mapping.column_values(vendor('A', employees='200-3000'), 'iPhone')
    assert values[settings.COMPANY_SIZE] == '1600'


@pytest.mark.parametrize('source', [None, '', 'LinkedIn', 'N/A'])
def test_company_size_without_a_source_page_is_left_empty(source):
    """gpt-4o-mini copied the example "51-200" (126) for three companies - no source, no number."""
    values = mapping.column_values(vendor('A', employees='51-200', employees_source_url=source), 'iPhone')
    assert settings.COMPANY_SIZE not in values


def test_year_founded_must_be_a_real_year():
    assert mapping.year_founded(1998) == 1998
    assert mapping.year_founded('seit 1998') == 1998
    assert mapping.year_founded(datetime.date.today().year + 1) is None
    assert mapping.year_founded(98) is None


@pytest.mark.parametrize('value, expected', [
    ('DE814093141', 'DE814093141'), ('DE 814 093 141', 'DE814093141'), ('de814093141', 'DE814093141'),
    ('DE123456789', ''), ('DE000000000', ''),
    ('ATU12345678', ''), ('DE12345', ''), ('Not found', ''),
])
def test_vat_id(value, expected):
    assert mapping.vat_id(value) == expected


@pytest.mark.parametrize('value, expected', [
    ('Manufacturer', 'Manufacturer'), ('Hersteller', 'Manufacturer'), ('official distributor', 'Distributor'),
    ('Großhändler', 'Distributor'), ('Fachhändler', 'Reseller'), ('Online shop', 'Reseller'), ('', ''), ('other', ''),
])
def test_vendor_type(value, expected):
    assert mapping.vendor_type(value) == expected


def test_regions_only_from_the_list():
    assert mapping.regions(['Bayern', 'Bavaria', 'Hessen', 'Wien', 'Europe']) == ['Bayern', 'Hessen']
    assert mapping.regions(['Bayern', 'deutschlandweit']) == ['Bundesweit'], 'nationwide stands alone'
    assert mapping.regions('NRW; Thüringen') == ['Nordrhein-Westfalen', 'Thüringen']
    assert mapping.regions(None) == []
    assert set(settings.REGIONS) >= set(mapping.REGION_ALIASES.values())


def test_all_16_states_listed_one_by_one_become_bundesweit():
    assert mapping.regions(list(settings.STATES)) == ['Bundesweit']
    assert mapping.regions(list(settings.STATES[:-1])) == list(settings.STATES[:-1]), '15 states stay as they are'


def test_certifications_trimmed_and_unique():
    assert mapping.certifications(['ISO 9001', 'iso 9001', '', 'ISO 14001']) == ['ISO 9001', 'ISO 14001']


def test_urls():
    assert mapping.url('www.firma.de') == 'https://www.firma.de'
    assert mapping.url('N/A') == ''
    assert mapping.linkedin('https://www.linkedin.com/company/firma') == 'https://www.linkedin.com/company/firma'
    assert mapping.linkedin('https://www.firma.de') == ''


def test_missing_values_are_left_out_never_placeholders():
    sparse = vendor('A', vat_id=None, year_founded=None, employees='unknown', description='', website='N/A',
                    linkedin='Not found', company_email='N/A', company_phone=None, contact_person=None,
                    contact_person_phone='unknown', vendor_type='other', delivery_regions=['Europe'],
                    certifications=[])
    values = mapping.column_values(sparse, 'iPhone')
    assert set(values) == {settings.SEARCH_SOURCE, settings.PRODUCT_NAME, settings.COUNTRY,
                           settings.LEGAL_NAME, settings.COMPLETE_ADDRESS}
    assert 'N/A' not in str(values)


def test_item_name_falls_back_to_the_legal_name():
    assert mapping.item_name(vendor('A', company_name=None)) == 'A GmbH'


@pytest.mark.parametrize('person, role, expected', [
    ('Heiner van Elten', 'Managing Director', ('Heiner van Elten', 'Managing Director')),
    ('Heiner van Elten, Managing Director', None, ('Heiner van Elten', 'Managing Director')),
    ('Sven Ebert, Verkauf & Kundenbetreuung', None, ('Sven Ebert', 'Verkauf & Kundenbetreuung')),
    ('Anna Schmidt - Vertrieb', None, ('Anna Schmidt', 'Vertrieb')),
    ('Anna Schmidt (Geschäftsführerin)', None, ('Anna Schmidt', 'Geschäftsführerin')),
    ('Hans-Peter Müller, CEO', None, ('Hans-Peter Müller', 'CEO')),
    ('Hans-Peter Müller', None, ('Hans-Peter Müller', '')),
    (None, 'Geschäftsführer', ('', 'Geschäftsführer')),
])
def test_the_contact_name_and_job_title_are_separated(person, role, expected):
    assert mapping.contact(vendor('A', contact_person=person, contact_person_role=role)) == expected


def test_the_contact_column_gets_the_name_and_job_functions_the_linked_title():
    values = mapping.column_values(vendor('A', contact_person='Heiner van Elten, Managing Director',
                                          contact_person_role=None), 'iPhone', 502)
    assert values[settings.CONTACT_PERSON] == 'Heiner van Elten'
    assert values[settings.JOB_FUNCTIONS] == {'item_ids': [502]}


def test_no_matching_title_leaves_job_functions_out():
    assert settings.JOB_FUNCTIONS not in mapping.column_values(vendor('A'), 'iPhone')


@pytest.mark.parametrize('address', [
    'Marienplatz 1, 80331 München, Germany',
    'Werner-von-Siemens-Str. 2, 86807 Buchloe, Deutschland',
    'Großheubacher Straße 4, 63897 Miltenberg',
    'Natt 18, 41334 Nettetal',
    'Hauptstraße 12a, 10115 Berlin',
    'Am Markt 3-5, 20095 Hamburg',
    'Siemensstr.7, 70469 Stuttgart',
])
def test_a_full_street_address_passes(address):
    assert matching.germany_problem(vendor('A', complete_address=address)) is None


@pytest.mark.parametrize('address, problem', [
    ('München, Germany', 'no postal code in the address'),
    ('80331 München', 'no street and house number in the address'),
    ('Hamburg, Deutschland', 'no postal code in the address'),
    ('Gewerbegebiet Nord, 12345 Musterstadt', 'no street and house number in the address'),
])
def test_an_address_without_street_number_or_postal_code_is_rejected(address, problem):
    """Papernet came through with "München, Germany" and a postal code given on its own."""
    assert matching.germany_problem(vendor('A', complete_address=address, postal_code='80331')) == problem



@pytest.mark.parametrize('link, expected', [
    ('https://www.a.de/downloads/katalog-2026.pdf', 'https://www.a.de/downloads/katalog-2026.pdf'),
    ('https://shop.a.de/katalog', 'https://shop.a.de/katalog'),          # a subdomain of their site
    ('https://www.other.de/a-katalog.pdf', ''),                          # not the vendor's own website
    ('https://www.a.de/products/iphone', ''),                            # the product page is not a catalogue
    ('https://www.a.de/products/iphone/', ''),
    (None, ''), ('N/A', ''),
])
def test_only_the_vendors_own_catalogue_is_used_never_the_product_page(link, expected):
    assert mapping.catalogue(vendor('A', catalogue_url=link)) == expected
