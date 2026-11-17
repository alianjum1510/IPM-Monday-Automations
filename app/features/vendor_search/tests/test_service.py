"""One run of Vendor Search, end to end, against the fake board and the fake AI."""
import pytest
import requests

from app.features.vendor_search import research, service, settings

from .conftest import BOARD, REQUEST_ID, candidate, vendor


def names(board):
    """
    Every vendor written - into the request (the best one) and as new items - in that order,
    from Legal Company Name (the items themselves are named after the product).
    """
    written = [values for _item_id, values in board.fills] + [item['values'] for item in board.created]
    return [values[settings.LEGAL_NAME].removesuffix(' GmbH') for values in written]


# ---- the request's status and group -----------------------------------------------------

def test_found_vendors_are_created_and_the_request_goes_ai_bot_then_research_completed(board, ai):
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones'), candidate('Gamma Tech')]

    summary = service.run(BOARD, REQUEST_ID)

    assert board.request_statuses == ['AI Bot', 'Research Completed']
    assert sorted(names(board)) == ['Alpha Mobile', 'Beta Phones', 'Gamma Tech']
    assert summary['result'] == 'Research Completed'
    assert summary['filled_request'] is True
    assert len(summary['created']) == 2, 'the best vendor went into the request; two new items'


def test_the_best_vendor_fills_the_request_so_no_empty_row_is_left(board, ai):
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]
    service.run(BOARD, REQUEST_ID)

    [(item_id, values)] = board.fills
    assert item_id == REQUEST_ID
    assert values[settings.LEGAL_NAME] == 'Alpha Mobile GmbH'
    assert values[settings.SEARCH_SOURCE] == {'label': 'Research Completed'}
    assert values[settings.PRODUCT_CATEGORIES] == {'labels': ['iPhone']}
    request = board.items[REQUEST_ID]
    assert request['name'] == 'iPhone', 'the request keeps its product name'
    assert request['legal_name'] == 'Alpha Mobile GmbH'
    assert [item['values'][settings.LEGAL_NAME] for item in board.created] == ['Beta Phones GmbH']


def test_if_the_request_cannot_be_filled_the_vendor_is_created_as_a_new_item(board, ai, monkeypatch):
    def broken(*args):
        raise service.monday.MondayError([{'message': 'nope'}])

    monkeypatch.setattr(service.monday, 'fill_request', broken)
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    summary = service.run(BOARD, REQUEST_ID)

    assert [item['values'][settings.LEGAL_NAME] for item in board.created] == ['Alpha Mobile GmbH', 'Beta Phones GmbH']
    assert summary['filled_request'] is False
    assert board.request_statuses[-1] == 'Research Completed'


def test_the_code_never_moves_the_request_the_boards_automation_does(board, ai):
    """With Sana's automation deleted, a completed request stays in group 1."""
    ai.candidates = [candidate('Alpha Mobile')]
    service.run(BOARD, REQUEST_ID)
    assert board.request_statuses[-1] == 'Research Completed'
    assert board.moves == []
    assert board.items[REQUEST_ID]['group'] == 'topics'


def test_a_request_with_nothing_found_stays_in_group_1(board, ai):
    ai.candidates = []
    service.run(BOARD, REQUEST_ID)
    assert board.request_statuses[-1] == 'Manual research'
    assert board.moves == []
    assert board.items[REQUEST_ID]['group'] == 'topics'


def test_a_request_whose_search_failed_stays_in_group_1(board, ai):
    ai.find_error = requests.ConnectionError('down')
    service.run(BOARD, REQUEST_ID)
    assert board.request_statuses[-1] == 'Manual research'
    assert board.moves == []


def test_ai_bot_is_set_before_any_search(board, ai, monkeypatch):
    statuses_when_asked = []

    def find(prompt, web_search=True):
        statuses_when_asked.append(list(board.request_statuses))
        return ai._answer({'candidates': []})

    monkeypatch.setattr(research, '_post', find)
    service.run(BOARD, REQUEST_ID)
    assert statuses_when_asked == [['AI Bot']], 'the request shows "AI Bot" before the AI is asked'
    assert board.request_statuses == ['AI Bot', 'Manual research']


def test_nothing_found_is_manual_research(board, ai):
    ai.candidates = []
    summary = service.run(BOARD, REQUEST_ID)
    assert board.request_statuses == ['AI Bot', 'Manual research']
    assert board.created == []
    assert summary['result'] == 'Manual research'


def test_ai_failing_after_every_retry_is_manual_research(board, ai):
    ai.find_error = requests.ConnectionError('down')
    summary = service.run(BOARD, REQUEST_ID)
    assert board.request_statuses == ['AI Bot', 'Manual research']
    assert 'failed after 4 attempt(s)' in summary['error']


def test_an_unexpected_error_still_ends_on_manual_research(board, ai, monkeypatch):
    def broken(*args):
        raise RuntimeError('unexpected')

    monkeypatch.setattr(service.monday, 'board_vendors', broken)
    summary = service.run(BOARD, REQUEST_ID)
    assert board.request_statuses == ['AI Bot', 'Manual research']
    assert summary['error'] == 'unexpected'


def test_a_request_with_nothing_found_is_not_filled(board, ai):
    ai.candidates = []
    service.run(BOARD, REQUEST_ID)
    assert board.fills == []
    assert board.items[REQUEST_ID]['legal_name'] == ''


# ---- what is ignored ----------------------------------------------------------------

def test_an_item_outside_the_vendor_search_group_is_ignored(board, ai):
    board.items[REQUEST_ID]['group'] = 'new_group'
    assert service.run(BOARD, REQUEST_ID)['result'] == 'ignored'
    assert board.status_writes == [] and ai.prompts == []


@pytest.mark.parametrize('source', ['AI Bot', 'Research Completed', 'Manual research', 'Inbound vendor'])
def test_an_item_with_search_source_set_is_ignored(board, ai, source):
    board.items[REQUEST_ID]['search_source'] = source
    assert service.run(BOARD, REQUEST_ID)['result'] == 'ignored'
    assert board.status_writes == [] and ai.prompts == []


def test_the_vendor_items_the_bot_creates_do_not_start_a_search(board, ai):
    """Their "item created" trigger reaches the app too; group 2 and a filled Search Source stop it."""
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]
    service.run(BOARD, REQUEST_ID)
    [new_vendor] = board.created
    prompts_before = len(ai.prompts)

    assert service.run(BOARD, new_vendor['id'])['result'] == 'ignored'
    assert len(ai.prompts) == prompts_before


def test_another_board_is_ignored(board, ai):
    assert service.run(123, REQUEST_ID)['result'] == 'ignored'
    assert ai.prompts == []


def test_a_deleted_item_is_ignored(board, ai):
    del board.items[REQUEST_ID]
    assert service.run(BOARD, REQUEST_ID)['result'] == 'ignored'


def test_a_second_trigger_while_searching_is_ignored(board, ai):
    service._running.add(REQUEST_ID)
    try:
        assert service.run(BOARD, REQUEST_ID)['reason'] == 'already being searched'
    finally:
        service._running.discard(REQUEST_ID)
    assert ai.prompts == []


def test_an_empty_product_name_is_manual_research(board, ai):
    board.items[REQUEST_ID]['name'] = '   '
    service.run(BOARD, REQUEST_ID)
    assert board.request_statuses == ['AI Bot', 'Manual research']
    assert ai.prompts == []


# ---- the vendor items ----------------------------------------------------------------

def test_a_vendor_item_is_named_after_the_product_and_created_in_group_2_with_every_column(board, ai):
    ai.candidates = [candidate('Best One'), candidate('Alpha Mobile')]
    service.run(BOARD, REQUEST_ID)
    [item] = board.created
    values = item['values']

    assert item['name'] == 'iPhone', 'named after the request, matching "Request (name of item)"'
    assert item['group'] == 'new_group'
    assert values[settings.SEARCH_SOURCE] == {'label': 'Research Completed'}
    assert values[settings.PRODUCT_CATEGORIES] == {'labels': ['iPhone']}
    assert values[settings.COUNTRY] == {'countryCode': 'DE', 'countryName': 'Germany'}
    assert values[settings.LEGAL_NAME] == 'Alpha Mobile GmbH'
    assert values[settings.VAT_ID] == 'DE123456789'
    assert values[settings.COMPANY_SIZE] == '250'
    assert values[settings.COMPANY_EMAIL] == {'email': 'info@alpha-mobile.de', 'text': 'info@alpha-mobile.de'}
    assert values[settings.CONTACT_PHONE] == {'phone': '+49897654321', 'countryShortName': 'DE'}
    assert values[settings.VENDOR_TYPE] == {'label': 'Distributor'}
    assert values[settings.DELIVERY_REGIONS] == {'labels': ['Bundesweit']}


def test_never_more_than_three_vendors(board, ai):
    ai.candidates = [candidate(f'Vendor {n}') for n in range(10)]
    summary = service.run(BOARD, REQUEST_ID)
    assert len(names(board)) == 3
    assert len(board.fills) == 1 and len(board.created) == 2
    assert len(ai.checks) == 3, 'only the top 3 are deep-checked when all pass'
    assert summary['ai_calls'] == 4


def test_fewer_good_vendors_means_fewer_items_never_weak_ones(board, ai):
    ai.candidates = [candidate('Good One'), candidate('Weak One')]
    ai.vendors['Weak One'] = vendor('Weak One', sells_exact_product=False)
    service.run(BOARD, REQUEST_ID)
    assert names(board) == ['Good One']
    assert board.request_statuses[-1] == 'Research Completed'


# ---- Germany only ----------------------------------------------------------------------

@pytest.mark.parametrize('overrides', [
    {'based_in_germany': False},
    {'country_code': 'AT', 'complete_address': 'Stephansplatz 1, 1010 Wien, Österreich', 'postal_code': '1010'},
    {'complete_address': 'Bahnhofstrasse 1, 8001 Zürich, Schweiz', 'postal_code': '8001'},
    {'address_source_url': None},
    {'complete_address': '', 'city': ''},
])
def test_a_vendor_not_based_in_germany_is_rejected_and_replaced(board, ai, overrides):
    ai.candidates = [candidate('Foreign Co'), candidate('A'), candidate('B'), candidate('C')]
    ai.vendors['Foreign Co'] = vendor('Foreign Co', **overrides)

    summary = service.run(BOARD, REQUEST_ID)

    assert 'Foreign Co' not in names(board)
    assert sorted(names(board)) == ['A', 'B', 'C'], 'the next candidate takes its place'
    assert any(r.startswith('Foreign Co:') for r in summary['rejected'])


def test_a_candidate_plainly_outside_germany_is_not_even_checked(board, ai):
    ai.candidates = [candidate('Vienna Phones', country='Austria', postal_code='1010'), candidate('A')]
    service.run(BOARD, REQUEST_ID)
    assert names(board) == ['A']
    assert len(ai.checks) == 1


def test_the_search_area_is_in_both_prompts(board, ai):
    ai.candidates = [candidate('A')]
    service.run(BOARD, REQUEST_ID)
    find, check = ai.prompts
    assert 'companies based in Germany' in find and 'even if it delivers to Germany' in find
    assert 'Confirm the company is based in Germany' in check


# ---- repeats -------------------------------------------------------------------------------

def test_a_vendor_already_on_the_board_for_the_product_is_not_returned_again(board, ai):
    board.add(500, 'Tech World', products=['iPhone'], search_source='AI Bot', website='https://www.tech-world.de')
    ai.candidates = [candidate('Tech World GmbH'), candidate('A'), candidate('B'), candidate('C')]

    summary = service.run(BOARD, REQUEST_ID)

    assert sorted(names(board)) == ['A', 'B', 'C']
    assert summary['repeats_skipped'] == 1
    assert '- Tech World (tech-world.de)' in ai.finds[0], 'the AI is told not to return it'


@pytest.mark.parametrize('request_name', ['iphone', ' iPhone ', 'IPHONE'])
def test_the_same_product_in_another_case_counts_as_a_repeat(board, ai, request_name):
    board.items[REQUEST_ID]['name'] = request_name
    board.add(500, 'Tech World', products=['iPhone'], search_source='AI Bot')
    board.dropdown_labels = ['iPhone']
    ai.candidates = [candidate('Tech World'), candidate('A')]

    service.run(BOARD, REQUEST_ID)

    assert names(board) == ['A']
    [(_item_id, values)] = board.fills
    assert values[settings.PRODUCT_CATEGORIES] == {'labels': ['iPhone']}, \
        'the existing label is reused, so "iphone" does not become a second label'


def test_iphone_15_is_a_different_product(board, ai):
    board.items[REQUEST_ID]['name'] = 'iPhone 15'
    board.add(500, 'Tech World', products=['iPhone'], search_source='AI Bot')
    ai.candidates = [candidate('Tech World')]

    service.run(BOARD, REQUEST_ID)

    assert names(board) == ['Tech World']
    [(_item_id, values)] = board.fills
    assert values[settings.PRODUCT_CATEGORIES] == {'labels': ['iPhone 15']}


def test_a_vendor_row_named_after_the_product_is_recognised_by_its_legal_name(board, ai):
    """Rows the bot creates are named "iPhone"; the company is in Legal Company Name."""
    board.add(500, 'iPhone', group='new_group', products=['iPhone'], search_source='Research Completed',
              legal_name='Tech World GmbH')
    ai.candidates = [candidate('Tech World'), candidate('A')]

    summary = service.run(BOARD, REQUEST_ID)

    assert names(board) == ['A']
    assert summary['repeats_skipped'] == 1
    assert '- Tech World GmbH' in ai.finds[0]
    assert '- iPhone' not in ai.finds[0], 'the product is not mistaken for a company name'


def test_a_second_search_for_the_same_product_returns_new_vendors(board, ai):
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]
    service.run(BOARD, REQUEST_ID)

    board.add(101, 'iphone')
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones'), candidate('Gamma Tech')]
    service.run(BOARD, 101)

    assert sorted(names(board)) == ['Alpha Mobile', 'Beta Phones', 'Gamma Tech']


def test_a_repeat_found_by_website_is_skipped(board, ai):
    board.add(500, 'TW Handels', products=['iPhone'], website='https://tech-world.de/')
    ai.candidates = [candidate('Tech World')]
    service.run(BOARD, REQUEST_ID)
    assert board.created == [] and board.fills == []
    assert board.request_statuses[-1] == 'Manual research'


def test_a_vendor_of_another_product_is_not_a_repeat(board, ai):
    board.add(500, 'Tech World', products=['Samsung Galaxy'])
    ai.candidates = [candidate('Tech World')]
    service.run(BOARD, REQUEST_ID)
    assert names(board) == ['Tech World']


def test_the_same_company_twice_in_one_answer_is_created_once(board, ai):
    ai.candidates = [candidate('Alpha Mobile'), candidate('Alpha Mobile GmbH'), candidate('B')]
    service.run(BOARD, REQUEST_ID)
    assert sorted(names(board)) == ['Alpha Mobile', 'B']


# ---- limits and failures --------------------------------------------------------------------

def test_at_most_six_deep_checks_per_request(board, ai):
    ai.candidates = [candidate(f'Vendor {n}') for n in range(10)]
    for n in range(10):
        ai.vendors[f'Vendor {n}'] = vendor(f'Vendor {n}', based_in_germany=False)

    summary = service.run(BOARD, REQUEST_ID)

    assert len(ai.checks) == settings.MAX_CHECKS == 6
    assert summary['checked'] == 6
    assert board.created == []
    assert board.request_statuses == ['AI Bot', 'Manual research']


def test_a_failed_check_is_replaced_by_the_next_candidate(board, ai):
    ai.candidates = [candidate('Broken'), candidate('A'), candidate('B'), candidate('C')]
    ai.vendors['Broken'] = research.ResearchError('the answer was not JSON')
    service.run(BOARD, REQUEST_ID)
    assert sorted(names(board)) == ['A', 'B', 'C']


def test_one_vendor_failing_to_be_created_does_not_lose_the_others(board, ai):
    ai.candidates = [candidate('A'), candidate('B')]
    board.reject = lambda values: ([{'message': 'nope', 'extensions': {'error_data': {'column_id': settings.SEARCH_SOURCE}}}]
                                   if values.get(settings.LEGAL_NAME) == 'A GmbH' else None)
    summary = service.run(BOARD, REQUEST_ID)
    assert names(board) == ['B']
    assert board.request_statuses[-1] == 'Research Completed'
    assert any(r.startswith('A: could not be created') for r in summary['rejected'])


def test_a_status_write_failing_is_logged_not_raised(board, ai, caplog):
    board.fail_status = True
    summary = service.run(BOARD, REQUEST_ID)
    assert summary['result'] == 'error'
    assert any('could not update item' in r.getMessage() for r in caplog.records)


# ---- ranking ---------------------------------------------------------------------------------

def test_better_verified_manufacturers_rank_first(board, ai, monkeypatch):
    monkeypatch.setattr(settings, 'VENDORS_WANTED', 2)
    ai.candidates = [candidate('Reseller Shop'), candidate('Maker'), candidate('No VAT')]
    ai.vendors['Reseller Shop'] = vendor('Reseller Shop', vendor_type='Reseller')
    ai.vendors['Maker'] = vendor('Maker', vendor_type='Manufacturer')
    ai.vendors['No VAT'] = vendor('No VAT', vat_id=None, vendor_type='Manufacturer')
    # Two wanted: the first two candidates are checked (both pass), the third is never needed.
    service.run(BOARD, REQUEST_ID)
    assert names(board) == ['Maker', 'Reseller Shop']


def test_rank_key_orders_by_verified_data_then_type_then_established_then_reachable():
    full = vendor('Full', vendor_type='Reseller')
    no_vat = vendor('No VAT', vat_id=None, vendor_type='Manufacturer')
    maker = vendor('Maker', vendor_type='Manufacturer')
    small = vendor('Small', vendor_type='Manufacturer', employees=3, year_founded=2024, linkedin=None)
    unreachable = vendor('Unreachable', vendor_type='Manufacturer', company_email=None, company_phone=None)
    ranked = sorted([(4, full), (3, no_vat), (2, maker), (1, small), (0, unreachable)],
                    key=lambda pair: service._rank_key(*pair))
    assert [v['company_name'] for _, v in ranked] == ['Maker', 'Unreachable', 'Small', 'Full', 'No VAT']


def test_the_dry_run_prints_the_vendors_and_writes_nothing(board, ai, capsys):
    from app.features.vendor_search import dry_run

    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]
    dry_run.main(['iPhone'])

    out = capsys.readouterr().out
    assert '--- Vendor 1: Alpha Mobile ---' in out and '--- Vendor 2: Beta Phones ---' in out
    assert 'Request would be set to: Research Completed' in out
    assert board.created == [] and board.status_writes == []


def test_the_run_is_summarised_in_one_log_line(board, ai, caplog):
    caplog.set_level('INFO', logger='vendor_search')
    ai.candidates = [candidate('A')]
    service.run(BOARD, REQUEST_ID)
    [line] = [r for r in caplog.records if r.getMessage().startswith('Vendor search done')]
    assert "product='iPhone'" in line.getMessage()
    assert line.payload['result'] == 'Research Completed'
    assert line.payload['item_id'] == str(REQUEST_ID)


# ---- same product, written differently --------------------------------------------------

EURO = 'Euro pallets'


def euro_pallets_on_the_board(board):
    """The first "Euro pallets" search: three vendors on the board."""
    for item_id, company in ((500, 'Krenzer'), (501, 'HTR Paletten'), (502, 'Falkenhahn')):
        board.add(item_id, EURO, group='new_group', products=[EURO], search_source='Research Completed',
                  legal_name=f'{company} GmbH', website=f'https://www.{company.lower().replace(" ", "-")}.de')
    board.dropdown_labels = [EURO]


@pytest.mark.parametrize('request_name', ['europallets', 'Euro-Pallets', 'EURO PALLETS'])
def test_the_same_product_without_spaces_or_hyphens_needs_no_ai_question(board, ai, request_name):
    euro_pallets_on_the_board(board)
    board.items[REQUEST_ID]['name'] = request_name
    ai.candidates = [candidate('Krenzer'), candidate('New Pallets')]

    summary = service.run(BOARD, REQUEST_ID)

    assert names(board) == ['New Pallets'], 'Krenzer is not returned again'
    assert ai.matches == [], 'decided in code'
    assert summary['same_product_labels'] == [EURO]
    [(_item_id, values)] = board.fills
    assert values[settings.PRODUCT_CATEGORIES] == {'labels': [EURO]}, 'the existing label is reused'


@pytest.mark.parametrize('request_name', ['eurppallets', 'Europaletten', 'Euro pallet'])
def test_a_typo_plural_or_translation_of_the_same_product_returns_no_existing_vendor(board, ai, request_name):
    euro_pallets_on_the_board(board)
    board.items[REQUEST_ID]['name'] = request_name
    ai.same_products = [EURO]
    ai.candidates = [candidate('Krenzer'), candidate('HTR Paletten'), candidate('Falkenhahn'),
                     candidate('New One'), candidate('New Two'), candidate('New Three')]

    summary = service.run(BOARD, REQUEST_ID)

    assert sorted(names(board)) == ['New One', 'New Three', 'New Two']
    assert summary['repeats_skipped'] == 3
    assert len(ai.matches) == 1 and request_name in ai.matches[0] and f'"{EURO}"' in ai.matches[0]
    assert ai.web_search[ai.prompts.index(ai.matches[0])] is False, 'the same-product question has no web search'
    assert all(values[settings.PRODUCT_CATEGORIES] == {'labels': [EURO]}
               for values in [v for _i, v in board.fills] + [item['values'] for item in board.created])


def test_a_different_product_may_return_a_vendor_already_on_the_board(board, ai):
    euro_pallets_on_the_board(board)
    board.items[REQUEST_ID]['name'] = 'Pen'
    ai.same_products = []
    ai.candidates = [candidate('Krenzer')]

    service.run(BOARD, REQUEST_ID)

    assert names(board) == ['Krenzer'], 'found for another product, so allowed'
    [(_item_id, values)] = board.fills
    assert values[settings.PRODUCT_CATEGORIES] == {'labels': ['Pen']}


def test_only_labels_from_the_board_are_accepted_from_the_ai(board, ai):
    euro_pallets_on_the_board(board)
    board.items[REQUEST_ID]['name'] = 'eurppallets'
    ai.same_products = ['Invented Label']
    ai.candidates = [candidate('Krenzer')]

    summary = service.run(BOARD, REQUEST_ID)

    assert summary['same_product_labels'] == []
    assert names(board) == ['Krenzer']


def test_if_the_same_product_question_fails_the_search_still_runs(board, ai):
    euro_pallets_on_the_board(board)
    board.items[REQUEST_ID]['name'] = 'eurppallets'
    ai.match_error = requests.ConnectionError('down')
    ai.candidates = [candidate('New One')]

    summary = service.run(BOARD, REQUEST_ID)

    assert names(board) == ['New One']
    assert summary['result'] == 'Research Completed'


def test_with_no_products_on_the_board_no_same_product_question_is_asked(board, ai):
    ai.candidates = [candidate('A')]
    service.run(BOARD, REQUEST_ID)
    assert ai.matches == []
