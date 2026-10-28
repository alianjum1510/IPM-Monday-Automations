"""
Placing a researched revenue figure into the board's revenue bands.

  pytest
"""
import json
import math
import re
from pathlib import Path

from app.features.company_enrichment.lib.mapping import build_column_values
from app.features.company_enrichment.lib.parse import parse_enrichment
from app.features.company_enrichment.lib.prompt import build_prompt
from app.features.company_enrichment.lib.revenue import band_for_figure, convert, parse_band, parse_figure, parse_number

boards = json.loads((Path(__file__).parent / 'boards.json').read_text())['data']['boards']
warm = next(b for b in boards if b['id'] == '5100825258')


def id_of(board, title):
    return next((c['id'] for c in board['columns'] if c['title'] == title), None)


# Estimated Annual Revenue as it stands on the warm board.
EUR_BANDS = ['< 1M EUR', '1M-10M EUR', '10M-50M EUR', '50M-100M EUR', '100M-500M EUR', '500M+ EUR']
USD_BANDS = ['< 1M USD', '1M-10M USD', '10M-50M USD', '50M+ USD']


def options(names):
    """The shape status_labels() hands over: ids from 1, in board order."""
    return [{'index': i + 1, 'label': label} for i, label in enumerate(names)]


def band_of(names, figure, rates=None):
    placed = band_for_figure(options(names), figure, rates)
    return placed.get('label') if placed else None


RATES = {'EUR': 1, 'USD': 1.25, 'PKR': 312.5, 'INR': 100}


def test_the_board_labels_read_as_half_open_ranges():
    assert parse_band('< 1M EUR') == {'min': 0, 'max': 1e6, 'currency': 'EUR'}
    assert parse_band('1M-10M EUR') == {'min': 1e6, 'max': 1e7, 'currency': 'EUR'}
    assert parse_band('500M+ EUR') == {'min': 5e8, 'max': math.inf, 'currency': 'EUR'}
    assert parse_band('$10M - $50M') == {'min': 1e7, 'max': 5e7, 'currency': 'USD'}
    assert parse_band('10-50 Mio. €') == {'min': 1e7, 'max': 5e7, 'currency': 'EUR'}
    assert parse_band('Up to 1M EUR') == {'min': 0, 'max': 1e6, 'currency': 'EUR'}
    assert parse_band('N/A') is None


def test_a_figure_on_an_edge_goes_to_the_band_it_opens_not_the_one_it_closes():
    assert band_of(EUR_BANDS, 'EUR 10,000,000') == '10M-50M EUR'
    assert band_of(EUR_BANDS, 'EUR 1,000,000') == '1M-10M EUR', '"< 1M" leaves 1M out'
    assert band_of(EUR_BANDS, 'EUR 999,999') == '< 1M EUR'
    assert band_of(EUR_BANDS, 'EUR 500,000,000') == '500M+ EUR', '"500M+" takes 500M in'


def test_the_way_companies_write_revenue_is_understood():
    cases = [
        ('EUR 30,000,000 (2024)', 30e6),
        ('€30 million', 30e6),
        ('30 Mio. EUR', 30e6),
        ('30,5 Mio. €', 30.5e6),
        ('1.500.000,00 €', 1.5e6),
        ('1,2 Mrd. EUR', 1.2e9),
        ('30.000 TEUR', 30e6),
        ('$1.2B', 1.2e9),
        ('Umsatz 2023: 30 Mio. EUR', 30e6),
        ('30-35 Mio. EUR', 32.5e6),
    ]
    for text, amount in cases:
        assert parse_figure(text)['amount'] == amount, text


def test_a_number_with_no_scale_is_not_mistaken_for_a_revenue():
    assert parse_figure('30') is None, 'a missing "million", not thirty euros'
    assert parse_figure('Not stated (2024)') is None
    assert band_for_figure(options(EUR_BANDS), '30', RATES) is None


def test_german_and_english_separators():
    assert parse_number('30.000.000') == 30000000
    assert parse_number('30,000,000') == 30000000
    assert parse_number('1,2') == 1.2
    assert parse_number('1.5') == 1.5
    assert parse_number('30.000') == 30000


def test_a_euro_figure_is_converted_before_it_is_placed_on_a_dollar_board():
    # 45M EUR is 56.25M USD: 10M-50M without the conversion, 50M+ with it.
    assert band_of(USD_BANDS, 'EUR 45,000,000', RATES) == '50M+ USD'

    placed = band_for_figure(options(USD_BANDS), 'EUR 45,000,000', RATES)
    assert placed['from'] == 'EUR'
    assert placed['currency'] == 'USD'
    assert placed['amount'] == 56.25e6


def test_a_dollar_figure_is_converted_before_it_is_placed_on_a_euro_board():
    # 62.5M USD is 50M EUR - exactly on the edge, so it opens 50M-100M.
    assert band_of(EUR_BANDS, 'USD 62,500,000', RATES) == '50M-100M EUR'


def test_currency_codes_are_whole_words_except_the_t_in_teur():
    assert parse_figure('Nokia 30 Mio. (no currency stated)')['currency'] == ''
    assert parse_figure('30.000 TEUR')['currency'] == 'EUR'
    assert parse_figure('US$ 30 million')['currency'] == 'USD'


def test_a_figure_with_no_currency_is_taken_to_be_in_the_board_currency():
    assert band_of(USD_BANDS, '45 million', RATES) == '10M-50M USD'


def test_no_rate_means_no_guess():
    assert convert(30e6, 'GBP', 'EUR', RATES) is None
    assert band_for_figure(options(EUR_BANDS), 'GBP 30,000,000', RATES) == {
        'reason': 'no exchange rate for GBP -> EUR',
    }
    assert re.search('no exchange rate', band_for_figure(options(EUR_BANDS), 'USD 30,000,000', None)['reason'])


def test_a_column_whose_options_are_not_numeric_bands_is_left_to_text_matching():
    placed = band_for_figure(options(['GmbH', 'AG', 'KG']), 'EUR 30,000,000', RATES)
    assert re.search('not numeric bands', placed['reason'])


def with_revenue_options(names):
    """The warm board with its revenue options set, as the live column has them."""
    return {
        **warm,
        'columns': [
            {**column, 'settings_str': json.dumps({'labels': [{'id': i + 1, 'name': name} for i, name in enumerate(names)]})}
            if column['title'] == 'Estimated Annual Revenue'
            else column
            for column in warm['columns']
        ],
    }


def test_the_figure_decides_the_band_over_the_band_the_model_picked():
    board = with_revenue_options(EUR_BANDS)
    fields = parse_enrichment('ESTIMATED_ANNUAL_REVENUE: 1M-10M EUR\nANNUAL_REVENUE_FIGURE: EUR 30,000,000 (2024)')
    result = build_column_values(board['columns'], fields)

    assert result['values'][id_of(board, 'Estimated Annual Revenue')] == {'ids': [3]}, '10M-50M EUR'
    assert result['banded'][0]['label'] == '10M-50M EUR'
    assert not any(e['title'] == 'Estimated Annual Revenue' for e in result['unmatched']), 'placed, not unmatched'
    assert re.search(
        r'Estimated Annual Revenue figure: EUR 30,000,000 \(2024\) - 30M EUR -> 10M-50M EUR',
        result['values'][id_of(board, 'Comments')]['text'],
    )


def test_with_no_figure_the_band_the_model_picked_is_used():
    board = with_revenue_options(EUR_BANDS)
    result = build_column_values(
        board['columns'],
        parse_enrichment('ESTIMATED_ANNUAL_REVENUE: 10M-50M EUR\nANNUAL_REVENUE_FIGURE: Not found'),
    )

    assert result['values'][id_of(board, 'Estimated Annual Revenue')] == {'ids': [3]}
    assert result['banded'] == []


def test_a_figure_that_cannot_be_placed_falls_back_to_the_model_band_and_says_why():
    board = with_revenue_options(EUR_BANDS)
    values = build_column_values(
        board['columns'],
        parse_enrichment('ESTIMATED_ANNUAL_REVENUE: 10M-50M EUR\nANNUAL_REVENUE_FIGURE: GBP 30,000,000'),
        {},
        {'rates': RATES, 'date': '2026-10-15'},
    )['values']

    assert values[id_of(board, 'Estimated Annual Revenue')] == {'ids': [3]}
    assert re.search(r'not placed \(no exchange rate for GBP -> EUR\)', values[id_of(board, 'Comments')]['text'])


def test_the_conversion_is_spelled_out_in_comments():
    board = with_revenue_options(USD_BANDS)
    values = build_column_values(
        board['columns'],
        parse_enrichment('ANNUAL_REVENUE_FIGURE: EUR 45,000,000 (2024)'),
        {},
        {'rates': RATES, 'date': '2026-10-15'},
    )['values']

    assert values[id_of(board, 'Estimated Annual Revenue')] == {'ids': [4]}, '50M+ USD'
    assert re.search(
        r'45M EUR = 56\.25M USD at exchange rate of 2026-10-15 -> 50M\+ USD',
        values[id_of(board, 'Comments')]['text'],
    )


def test_the_prompt_asks_for_the_raw_figure():
    assert re.search(r'ANNUAL_REVENUE_FIGURE: \[', build_prompt('Muster GmbH', 'Badstraße 115, 71336 Waiblingen'))


def test_pakistani_and_indian_amounts_are_read():
    cases = [
        ('PKR 50 crore', 50e7),
        ('PKR 20 lakh', 20e5),
        ('PKR 20,00,000', 2e6),
        ('PKR 1,25,00,000', 12.5e6),
        ('PKR 2 arab', 2e9),
        ('INR 3.5 crore (2024)', 3.5e7),
    ]
    for text, amount in cases:
        assert parse_figure(text)['amount'] == amount, text
    assert parse_figure('PKR 50 crore')['currency'] == 'PKR'
    assert parse_figure('₹ 3 crore')['currency'] == 'INR'
    assert parse_figure('try 30 Mio.')['currency'] == '', '"try" is not Turkish lira'


def test_a_dollar_revenue_range_is_converted_to_euros_and_lands_in_the_euro_band():
    # Programmers Force: "$10M-$50M" -> 30M USD by the midpoint -> 24M EUR at 1.25.
    assert band_of(EUR_BANDS, 'USD 10M-50M (estimate, Crunchbase)', RATES) == '10M-50M EUR'
    assert band_of(EUR_BANDS, '$10M-$50M', RATES) == '10M-50M EUR'
    # 10M USD alone is 8M EUR - below 10M, so 1M-10M EUR.
    assert band_of(EUR_BANDS, 'USD 10,000,000', RATES) == '1M-10M EUR'


def test_a_rupee_revenue_is_converted_to_euros_and_lands_in_the_euro_band():
    # 500 crore PKR = 5bn PKR = 16M EUR at 312.5.
    assert band_of(EUR_BANDS, 'PKR 500 crore (2023)', RATES) == '10M-50M EUR'
    assert band_of(EUR_BANDS, 'PKR 20 lakh', RATES) == '< 1M EUR'


def test_rs_alone_is_not_placed_it_could_be_several_currencies():
    assert re.search('no ISO code', band_for_figure(options(EUR_BANDS), 'Rs 50 crore', RATES)['reason'])


def test_with_no_band_containing_the_figure_the_nearest_one_is_taken():
    gappy = ['1M-10M EUR', '50M-100M EUR']
    assert band_of(gappy, 'EUR 20,000,000', RATES) == '1M-10M EUR', '10M away vs 30M away'
    assert band_of(gappy, 'EUR 40,000,000', RATES) == '50M-100M EUR'
    assert band_for_figure(options(gappy), 'EUR 40,000,000', RATES)['nearest'] is True
    assert band_of(['10M EUR', '50M EUR', '100M EUR'], 'EUR 11,000,000', RATES) == '10M EUR', 'point options'


def test_the_models_own_band_answer_is_converted_when_it_is_not_an_option():
    board = with_revenue_options(EUR_BANDS)
    values = build_column_values(
        board['columns'],
        parse_enrichment('ESTIMATED_ANNUAL_REVENUE: $10M-$50M\nANNUAL_REVENUE_FIGURE: Not found'),
        {},
        {'rates': RATES, 'date': '2026-10-26'},
    )['values']

    assert values[id_of(board, 'Estimated Annual Revenue')] == {'ids': [3]}, '10M-50M EUR'
    assert re.search(
        r'30M USD = 24M EUR at exchange rate of 2026-10-26 -> 10M-50M EUR',
        values[id_of(board, 'Comments')]['text'],
    )
