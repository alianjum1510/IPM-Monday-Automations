"""The product page check (pages.py), with fetch() faked by the product_pages fixture."""
import pytest
import requests

from app.features.vendor_search import pages, service

from .conftest import BOARD, REQUEST_ID, candidate, vendor

FILLER = 'Willkommen bei uns. ' * 40


def page(*words):
    return 200, '<html><body>' + FILLER + ' '.join(words) + '</body></html>'


def hardi(**overrides):
    """What gpt-4o-mini returned for "zzqlorp 8812": a real company, an invented product."""
    return vendor('HARDI Automotive', website='https://www.hardi-automotive.com',
                  product_evidence_url='https://www.hardi-automotive.com/produkte',
                  product_terms=['zzqlorp 8812'], **overrides)


def test_a_page_that_shows_the_product_passes(product_pages):
    product_pages['default'] = page('Unsere Euro pallets nach EPAL')
    assert pages.product_page_problem(vendor('A', product_terms=[]), 'Euro pallets') is None


def test_the_word_the_page_uses_counts_too(product_pages):
    """An English request, a German page: the AI names the page's own word."""
    product_pages['default'] = page('Industriereiniger für Hallenböden')
    v = vendor('A', product_terms=['Industriereiniger'])
    assert pages.product_page_problem(v, 'industrial floor cleaner') is None


def test_an_invented_product_is_rejected(product_pages):
    product_pages['default'] = page('Elektrische Kraftstoffpumpen für Industrie und Landwirtschaft')
    assert pages.product_page_problem(hardi(), 'zzqlorp 8812') == 'product page does not mention the product'


@pytest.mark.parametrize('status', [404, 410])
def test_a_page_that_does_not_exist_is_rejected(product_pages, status):
    product_pages['default'] = (status, 'Not found')
    assert pages.product_page_problem(vendor('A'), 'iPhone') == f'product page does not exist (HTTP {status})'


def test_a_website_that_does_not_exist_is_rejected(product_pages):
    product_pages['default'] = requests.ConnectionError('no such host')
    assert 'cannot be reached' in pages.product_page_problem(vendor('A'), 'iPhone')


def test_a_marketplace_page_is_not_the_companys_own(product_pages):
    v = vendor('hinzkunst', website='https://www.hinzkunst.de',
               product_evidence_url='https://selekkt.com/brands/hinzkunst')
    assert pages.product_page_problem(v, 'xyz') == 'product page is not on the company website (selekkt.com)'
    assert product_pages['opened'] == [], 'not even opened'


def test_the_same_company_on_another_country_domain_is_its_own(product_pages):
    v = vendor('B. Braun', website='https://www.bbraun.de', product_evidence_url='https://www.bbraun.com/gloves')
    assert pages.product_page_problem(v, 'Produkt') is None


@pytest.mark.parametrize('answer', [
    (403, 'Forbidden'), (429, 'Too many'), (503, 'Down'),
    requests.Timeout('slow'),
    (200, '<html><body><div id="app"></div><script>render()</script></body></html>'),
])
def test_when_the_page_cannot_be_read_the_vendor_is_not_rejected(product_pages, answer):
    """Blocked, slow or built by JavaScript: the check cannot tell, so it does not reject."""
    product_pages['default'] = answer
    assert pages.product_page_problem(hardi(), 'zzqlorp 8812') is None


def test_scripts_and_tags_are_not_read_as_page_text():
    text = pages.page_text('<p>Euro&nbsp;pallets</p><script>var zzqlorp = 1</script><style>.x{}</style>')
    assert 'euro pallets' in text and 'zzqlorp' not in text


@pytest.mark.parametrize('url, name', [
    ('https://www.bbraun.de/x', 'bbraun'), ('https://shop.smurfitwestrock.com', 'smurfitwestrock'),
    ('https://www.example.co.uk/a', 'example'), ('', ''),
])
def test_site_name(url, name):
    assert pages.site_name(url) == name


# ---- in a whole run -------------------------------------------------------------------------

def test_an_invented_vendor_is_rejected_and_the_request_goes_to_manual_research(board, ai, product_pages):
    board.items[REQUEST_ID]['name'] = 'zzqlorp 8812'
    ai.candidates = [candidate('HARDI Automotive', website='https://www.hardi-automotive.com')]
    ai.vendors['HARDI Automotive'] = hardi()
    product_pages['default'] = page('Elektrische Kraftstoffpumpen')

    summary = service.run(BOARD, REQUEST_ID)

    assert board.fills == [] and board.created == []
    assert board.request_statuses == ['AI Bot', 'Manual research']
    assert any('does not mention the product' in reason for reason in summary['rejected'])


def test_a_vendor_whose_page_fails_is_replaced_by_the_next(board, ai, product_pages):
    ai.candidates = [candidate('Fake Shop'), candidate('A'), candidate('B'), candidate('C')]
    product_pages['urls']['https://www.fake-shop.de/products/iphone'] = (404, 'Not found')

    service.run(BOARD, REQUEST_ID)

    from .test_service import names
    assert sorted(names(board)) == ['A', 'B', 'C']
