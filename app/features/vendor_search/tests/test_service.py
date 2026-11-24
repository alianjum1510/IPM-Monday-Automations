"""One run of Vendor Search, end to end, against the fake board and the fake AI."""
import pytest
import requests

from app.features.vendor_search import research, service, settings

from .conftest import BOARD, REQUEST_ID, candidate, vendor


def names(board):
    """
    Every vendor written - into the request (the best one) and as new items - in that order,
    from Legal Company Name.
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
    assert values[settings.PRODUCT_NAME] == 'iPhone'
    request = board.items[REQUEST_ID]
    assert values['name'] == 'Alpha Mobile'
    assert request['name'] == 'Alpha Mobile', 'the request is renamed from the product to the vendor'
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

def test_a_vendor_item_is_named_after_the_vendor_and_created_in_group_2_with_every_column(board, ai):
    ai.candidates = [candidate('Best One'), candidate('Alpha Mobile')]
    service.run(BOARD, REQUEST_ID)
    [item] = board.created
    values = item['values']

    assert item['name'] == 'Alpha Mobile', 'named after the vendor, not the product'
    assert item['group'] == 'topics', 'created in group 1 ...'
    assert board.moves == [(item['id'], 'new_group')], '... then moved to group 2, like the request'
    assert board.items[item['id']]['group'] == 'new_group'
    assert values[settings.SEARCH_SOURCE] == {'label': 'Research Completed'}
    assert values[settings.PRODUCT_NAME] == 'iPhone'
    assert values[settings.COUNTRY] == {'countryCode': 'DE', 'countryName': 'Germany'}
    assert values[settings.LEGAL_NAME] == 'Alpha Mobile GmbH'
    assert values[settings.VAT_ID] == 'DE814093141'
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
    assert summary['ai_calls'] == 5, 'find + 3 checks + 1 category pick (the request has no category)'


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
    find, check = ai.finds[0], ai.checks[0]
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
    ai.candidates = [candidate('Tech World'), candidate('A')]

    service.run(BOARD, REQUEST_ID)

    assert names(board) == ['A']
    [(_item_id, values)] = board.fills
    assert values[settings.PRODUCT_NAME] == 'iPhone', \
        'the existing label is reused, so "iphone" does not become a second label'


def test_iphone_15_is_a_different_product(board, ai):
    board.items[REQUEST_ID]['name'] = 'iPhone 15'
    board.add(500, 'Tech World', products=['iPhone'], search_source='AI Bot')
    ai.candidates = [candidate('Tech World')]

    service.run(BOARD, REQUEST_ID)

    assert names(board) == ['Tech World']
    [(_item_id, values)] = board.fills
    assert values[settings.PRODUCT_NAME] == 'iPhone 15'


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

def test_at_most_twelve_deep_checks_over_two_search_rounds(board, ai):
    ai.find_rounds = [[candidate(f'Vendor {n}') for n in range(10)],
                      [candidate(f'Other {n}') for n in range(10)]]
    for name in [f'Vendor {n}' for n in range(10)] + [f'Other {n}' for n in range(10)]:
        ai.vendors[name] = vendor(name, based_in_germany=False)

    summary = service.run(BOARD, REQUEST_ID)

    assert len(ai.finds) == settings.FIND_ROUNDS == 2
    assert len(ai.checks) == settings.MAX_CHECKS == 12
    assert summary['checked'] == 12
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
    assert values[settings.PRODUCT_NAME] == EURO, 'the existing label is reused'


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
    assert all(values[settings.PRODUCT_NAME] == EURO
               for values in [v for _i, v in board.fills] + [item['values'] for item in board.created])


def test_a_different_product_may_return_a_vendor_already_on_the_board(board, ai):
    euro_pallets_on_the_board(board)
    board.items[REQUEST_ID]['name'] = 'Pen'
    ai.same_products = []
    ai.candidates = [candidate('Krenzer')]

    service.run(BOARD, REQUEST_ID)

    assert names(board) == ['Krenzer'], 'found for another product, so allowed'
    [(_item_id, values)] = board.fills
    assert values[settings.PRODUCT_NAME] == 'Pen'


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


def test_nothing_found_keeps_the_product_name_on_the_request(board, ai):
    ai.candidates = []
    service.run(BOARD, REQUEST_ID)
    assert board.items[REQUEST_ID]['name'] == 'iPhone'
    assert board.fills == [] and board.created == []
    assert board.request_statuses == ['AI Bot', 'Manual research']


# ---- contact job title -> Job Functions ------------------------------------------------

def test_a_title_written_as_on_the_job_functions_board_is_linked_without_an_ai_question(board, ai):
    ai.candidates = [candidate('Alpha Mobile')]
    service.run(BOARD, REQUEST_ID)
    [(_item, values)] = board.fills
    assert values[settings.CONTACT_PERSON] == 'Anna Schmidt'
    assert values[settings.JOB_FUNCTIONS] == {'item_ids': [502]}
    assert ai.job_questions == []


def test_a_title_in_another_language_is_matched_by_one_ai_question(board, ai):
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]
    ai.vendors['Alpha Mobile'] = vendor('Alpha Mobile', contact_person='Heiner van Elten, Managing Director',
                                        contact_person_role=None)
    ai.vendors['Beta Phones'] = vendor('Beta Phones', contact_person_role='CEO')
    ai.job_matches = {'Managing Director': 'Geschäftsführer', 'CEO': 'Geschäftsführer'}

    summary = service.run(BOARD, REQUEST_ID)

    assert len(ai.job_questions) == 1, 'one question for all the titles'
    assert '"Managing Director"' in ai.job_questions[0] and '"Geschäftsführer"' in ai.job_questions[0]
    assert ai.web_search[ai.prompts.index(ai.job_questions[0])] is False
    written = [values for _item, values in board.fills] + [item['values'] for item in board.created]
    assert [v[settings.JOB_FUNCTIONS] for v in written] == [{'item_ids': [501]}] * 2, 'the first Geschäftsführer'
    assert written[0][settings.CONTACT_PERSON] == 'Heiner van Elten'
    assert summary['job_functions'] == {'Managing Director': 'Geschäftsführer', 'CEO': 'Geschäftsführer'}


def test_a_title_the_ai_cannot_match_or_invents_is_left_empty(board, ai):
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]
    ai.vendors['Alpha Mobile'] = vendor('Alpha Mobile', contact_person_role='Lagerist')
    ai.vendors['Beta Phones'] = vendor('Beta Phones', contact_person_role='Chief Happiness Officer')
    ai.job_matches = {'Lagerist': None, 'Chief Happiness Officer': 'Glücksbeauftragter'}
    service.run(BOARD, REQUEST_ID)
    written = [values for _item, values in board.fills] + [item['values'] for item in board.created]
    assert all(settings.JOB_FUNCTIONS not in v for v in written)
    assert board.request_statuses[-1] == 'Research Completed'


def test_job_functions_failing_never_stops_the_vendors(board, ai):
    board.job_titles_error = service.monday.MondayError([{'message': 'no access'}])
    ai.candidates = [candidate('Alpha Mobile')]
    service.run(BOARD, REQUEST_ID)
    [(_item, values)] = board.fills
    assert settings.JOB_FUNCTIONS not in values and values[settings.CONTACT_PERSON] == 'Anna Schmidt'
    assert board.request_statuses[-1] == 'Research Completed'


def test_no_contact_title_asks_nothing(board, ai):
    ai.candidates = [candidate('Alpha Mobile')]
    ai.vendors['Alpha Mobile'] = vendor('Alpha Mobile', contact_person='Anna Schmidt', contact_person_role=None)
    service.run(BOARD, REQUEST_ID)
    assert ai.job_questions == []


# ---- always 3: a second search round --------------------------------------------------------

def test_when_the_first_round_gives_fewer_than_3_a_second_round_finds_the_rest(board, ai):
    ai.find_rounds = [[candidate('Good One'), candidate('Bad One'), candidate('Bad Two')],
                      [candidate('Bad One'), candidate('Good Two'), candidate('Good Three')]]
    ai.vendors['Bad One'] = vendor('Bad One', sells_exact_product=False)
    ai.vendors['Bad Two'] = vendor('Bad Two', based_in_germany=False)

    summary = service.run(BOARD, REQUEST_ID)

    assert sorted(names(board)) == ['Good One', 'Good Three', 'Good Two']
    assert summary['rounds'] == 2 and summary['verified'] == 3
    assert '- Bad One' in ai.finds[1] and '- Good One' in ai.finds[1], 'the 2nd round is told who was tried'
    assert len(ai.checks) == 5, 'Bad One, named again, is not checked twice'
    assert board.request_statuses[-1] == 'Research Completed'


def test_no_second_round_when_the_first_gives_3(board, ai):
    ai.find_rounds = [[candidate('A'), candidate('B'), candidate('C')], [candidate('D')]]
    summary = service.run(BOARD, REQUEST_ID)
    assert len(ai.finds) == 1 and summary['rounds'] == 1
    assert sorted(names(board)) == ['A', 'B', 'C']


def test_a_failed_second_round_keeps_the_vendors_already_found(board, ai):
    ai.find_rounds = [[candidate('A')], requests.ConnectionError('down')]
    service.run(BOARD, REQUEST_ID)
    assert names(board) == ['A']
    assert board.request_statuses[-1] == 'Research Completed'


def test_a_second_round_with_nothing_new_stops(board, ai):
    ai.find_rounds = [[candidate('A')], [candidate('A GmbH')]]
    summary = service.run(BOARD, REQUEST_ID)
    assert summary['rounds'] == 2 and len(ai.checks) == 1
    assert names(board) == ['A']



# ---- Product Category: the request's, copied to every new vendor row -----------------------

CLEANING = 'Cleaning & Hygiene'


def test_the_new_vendor_rows_get_the_requests_product_category(board, ai):
    board.items[REQUEST_ID]['category'] = [CLEANING]
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones'), candidate('Gamma Tech')]

    summary = service.run(BOARD, REQUEST_ID)

    assert len(board.created) == 2
    assert all(item['values'][settings.PRODUCT_CATEGORY] == {'labels': [CLEANING]} for item in board.created)
    [(_item_id, request_values)] = board.fills
    assert settings.PRODUCT_CATEGORY not in request_values, 'the request row keeps its own category untouched'
    assert summary['product_category'] == [CLEANING]


def test_only_one_category_is_written_even_when_the_request_has_several(board, ai):
    board.items[REQUEST_ID]['category'] = [CLEANING, 'Packaging']
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones'), candidate('Gamma Tech')]

    service.run(BOARD, REQUEST_ID)

    assert all(item['values'][settings.PRODUCT_CATEGORY] == {'labels': [CLEANING]} for item in board.created)
    assert ai.category_questions == []


def test_a_category_set_on_the_request_during_the_search_is_still_copied(board, ai, monkeypatch):
    """Read when the vendors are written, not when the search starts."""
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    def set_category_then_answer(prompt, web_search=True):
        board.items[REQUEST_ID]['category'] = [CLEANING]
        return ai.post(prompt, web_search)

    monkeypatch.setattr(research, '_post', set_category_then_answer)

    service.run(BOARD, REQUEST_ID)

    [item] = board.created
    assert item['values'][settings.PRODUCT_CATEGORY] == {'labels': [CLEANING]}


def test_without_a_category_on_the_request_the_ai_picks_one_for_every_row(board, ai):
    """A request typed by hand has no purchase requirement, so no category: the AI picks one."""
    board.items[REQUEST_ID]['name'] = 'Glass cleaner'
    ai.category = CLEANING
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones'), candidate('Gamma Tech')]

    summary = service.run(BOARD, REQUEST_ID)

    [(_item_id, request_values)] = board.fills
    assert request_values[settings.PRODUCT_CATEGORY] == {'labels': [CLEANING]}, 'the request row gets it too'
    assert all(item['values'][settings.PRODUCT_CATEGORY] == {'labels': [CLEANING]} for item in board.created)
    [question] = ai.category_questions
    assert '"Glass cleaner"' in question and '- "Packaging"' in question, 'asked with the product and the options'
    assert ai.web_search[ai.prompts.index(question)] is False, 'no web search for the category'
    assert summary['product_category_by_ai'] is True


def test_the_ai_is_not_asked_when_the_request_has_a_category(board, ai):
    board.items[REQUEST_ID]['category'] = ['Packaging']
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    service.run(BOARD, REQUEST_ID)

    assert ai.category_questions == []
    assert board.created[0]['values'][settings.PRODUCT_CATEGORY] == {'labels': ['Packaging']}


def test_when_no_category_fits_the_ai_names_a_new_one_for_every_row(board, ai):
    """Basketball got "Other": now the AI names a broad new category, created on the board."""
    board.items[REQUEST_ID]['name'] = 'Basketball'
    ai.category = 'Sports & Leisure'
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones'), candidate('Gamma Tech')]

    summary = service.run(BOARD, REQUEST_ID)

    [(_item_id, request_values)] = board.fills
    assert request_values[settings.PRODUCT_CATEGORY] == {'labels': ['Sports & Leisure']}
    assert all(item['values'][settings.PRODUCT_CATEGORY] == {'labels': ['Sports & Leisure']}
               for item in board.created)
    assert summary['product_category_new'] is True


def test_a_category_created_earlier_is_offered_and_reused(board, ai):
    board.category_options = ['Cleaning & Hygiene', 'Other', 'Sports & Leisure']
    ai.category = 'sports & leisure'
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    summary = service.run(BOARD, REQUEST_ID)

    [question] = ai.category_questions
    assert '- "Sports & Leisure"' in question, 'the AI sees the category created by an earlier search'
    assert board.created[0]['values'][settings.PRODUCT_CATEGORY] == {'labels': ['Sports & Leisure']}
    assert summary['product_category_new'] is False


@pytest.mark.parametrize('answer', ['iPhone', None])
def test_an_unusable_ai_answer_writes_no_category(board, ai, answer):
    ai.category = answer
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    service.run(BOARD, REQUEST_ID)

    [(_item_id, request_values)] = board.fills
    assert settings.PRODUCT_CATEGORY not in request_values
    assert settings.PRODUCT_CATEGORY not in board.created[0]['values']


def test_if_the_category_question_fails_the_vendors_are_still_written(board, ai):
    ai.category_error = requests.Timeout('slow')
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    summary = service.run(BOARD, REQUEST_ID)

    assert sorted(names(board)) == ['Alpha Mobile', 'Beta Phones']
    assert settings.PRODUCT_CATEGORY not in board.created[0]['values']
    assert summary['result'] == 'Research Completed'


def test_no_vendor_found_asks_no_category_question(board, ai):
    ai.candidates = []

    service.run(BOARD, REQUEST_ID)

    assert ai.category_questions == []


def test_when_the_category_cannot_be_read_the_vendors_are_still_written(board, ai):
    """Unknown: the AI is not asked either, so a category the request may have is never overwritten."""
    board.items[REQUEST_ID]['category'] = [CLEANING]
    board.category_error = requests.ConnectionError('monday down for a moment')
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    summary = service.run(BOARD, REQUEST_ID)

    assert sorted(names(board)) == ['Alpha Mobile', 'Beta Phones']
    assert settings.PRODUCT_CATEGORY not in board.created[0]['values']
    assert summary['result'] == 'Research Completed'
    assert ai.category_questions == []



# ---- Catalogue / Documents: the vendor's own catalogue as a link, or nothing ---------------

def catalogue_of(name):
    return f'https://www.{name.lower().replace(" ", "-")}.de/katalog.pdf'


def test_a_vendors_catalogue_is_added_as_a_link_to_its_row(board, ai):
    ai.vendors = {name: vendor(name, catalogue_url=catalogue_of(name)) for name in ('Alpha Mobile', 'Beta Phones')}
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    summary = service.run(BOARD, REQUEST_ID)

    new_id = board.created[0]['id']
    assert board.catalogues == [
        (REQUEST_ID, [{'fileType': 'link', 'name': 'Catalogue - Alpha Mobile', 'linkToFile': catalogue_of('Alpha Mobile')}]),
        (new_id, [{'fileType': 'link', 'name': 'Catalogue - Beta Phones', 'linkToFile': catalogue_of('Beta Phones')}]),
    ]
    assert summary['catalogues'] == 2


def test_no_catalogue_leaves_the_column_empty_never_the_product_page(board, ai):
    ai.vendors = {'Alpha Mobile': vendor('Alpha Mobile', catalogue_url=None),
                  'Beta Phones': vendor('Beta Phones', catalogue_url='https://www.beta-phones.de/products/iphone')}
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    service.run(BOARD, REQUEST_ID)

    assert board.catalogues == []


def test_a_file_attached_to_the_request_by_hand_is_never_replaced(board, ai):
    board.items[REQUEST_ID]['files'] = ['purchase-spec.pdf']
    ai.vendors = {'Alpha Mobile': vendor('Alpha Mobile', catalogue_url=catalogue_of('Alpha Mobile'))}
    ai.candidates = [candidate('Alpha Mobile')]

    service.run(BOARD, REQUEST_ID)

    assert board.catalogues == []
    assert board.items[REQUEST_ID]['files'] == ['purchase-spec.pdf']


def test_a_failed_catalogue_link_does_not_stop_the_vendors(board, ai):
    board.catalogue_error = requests.ConnectionError('monday down for a moment')
    ai.vendors = {name: vendor(name, catalogue_url=catalogue_of(name)) for name in ('Alpha Mobile', 'Beta Phones')}
    ai.candidates = [candidate('Alpha Mobile'), candidate('Beta Phones')]

    summary = service.run(BOARD, REQUEST_ID)

    assert sorted(names(board)) == ['Alpha Mobile', 'Beta Phones']
    assert summary['result'] == 'Research Completed'
