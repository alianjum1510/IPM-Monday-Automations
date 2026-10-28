"""
Places a researched revenue figure into one of the board's revenue bands.

Text matching alone (find_status_label) only accepts an answer that already
spells a band - "€30 million" never matches "15M-30M EUR". So the research
also returns the raw figure, and this module does the arithmetic:

  1. the bands are read from the column's CURRENT options, not a list in the
     code - "< 1M EUR" is [0, 1M), "1M-10M EUR" is [1M, 10M), "500M+ EUR" is
     [500M, infinity) - so renaming or re-cutting the bands needs no deploy;
  2. the figure is converted into the bands' currency (USD or PKR -> EUR,
     or EUR -> USD when the board's options are in dollars) with the day's
     rates;
  3. the band whose range contains it wins.

Every band includes its lower bound and excludes its upper one, so a figure
on an edge has exactly one home: 30M goes to "30M-50M", not "15M-30M". The
board's own labels already read that way - "< 1M" leaves 1M out and "500M+"
takes 500M in.

Pure: the exchange rates are passed in (services/fx.py fetches them), so
this is testable without a network.
"""
import math
import re
from decimal import ROUND_HALF_UP, Decimal

# Multipliers, longest spelling first so "mio" is not read as "m". Lakh (1e5),
# crore (1e7) and arab (1e9) are how Pakistani and Indian sources state
# revenue: "PKR 50 crore" is 500 million rupees.
MULTIPLIERS = [
    (re.compile(r'(?:milliarden?|mrd\.?|billions?|bn|b|arabs?)', re.IGNORECASE), 1e9),
    (re.compile(r'(?:crores?|cr\.?)', re.IGNORECASE), 1e7),
    (re.compile(r'(?:millionen|millions?|mio\.?|mn|m)', re.IGNORECASE), 1e6),
    (re.compile(r'(?:lakhs?|lacs?)', re.IGNORECASE), 1e5),
    (re.compile(r'(?:tausend|thousand|tsd\.?|k|t)', re.IGNORECASE), 1e3),
]

# A number with an optional multiplier after it. "T" only counts in front of a
# currency - "30.000 TEUR" / "30.000 T€" is how German accounts write thousands.
# Digit groups of two are accepted for the Pakistani/Indian grouping
# ("20,00,000" is 20 lakh); parse_number decides what the separators mean.
AMOUNT = re.compile(
    r'(\d+(?:[.,]\d{2,3}|\s\d{3})*(?:[.,]\d+)?)\s*'
    r'(?:(milliarden?|mrd\.?|billions?|bn|arabs?|crores?|cr\.?|millionen|millions?|mio\.?|mn|lakhs?|lacs?'
    r'|tausend|thousand|tsd\.?|[bmk])(?![a-z])|(t)(?=\s*(?:€|eur)))?',
    re.IGNORECASE,
)

# Joins two amounts into a range: "1M-10M", "1 to 10 Mio.", "1 bis 10".
RANGE_JOIN = re.compile(r'^\s*(?:-|–|—|to|bis)\s*[^\d]{0,6}$', re.IGNORECASE)

# Words that make a single amount an open-ended band.
BELOW = re.compile(r'(?:^|\s)(?:<|≤|under|below|less than|up to|bis|unter|weniger als)\s*[^\d]{0,4}$', re.IGNORECASE)
ABOVE = re.compile(r'(?:^|[^a-zäöü])(?:[>≥]|(?:over|above|more than|über|ueber|ab|from)\s)[^\d]*$', re.IGNORECASE)
PLUS_AFTER = re.compile(r'^\s*[a-z€$£.\s]*\+', re.IGNORECASE)


def _iso_code(iso):
    return re.compile(r'(?<![A-Za-z])' + iso + r'(?![A-Za-z])')


# ISO codes first, then symbols, then words. Codes are whole upper-case words,
# so "Nokia" is not kroner and "try" is not Turkish lira - except EUR, which
# German accounts prefix with T ("TEUR").
ISO_CODES = [
    'GBP', 'CHF', 'PLN', 'CZK', 'SEK', 'NOK', 'DKK', 'HUF', 'RON', 'BGN', 'TRY', 'ISK', 'UAH', 'RUB',
    'PKR', 'INR', 'BDT', 'LKR', 'AED', 'SAR', 'QAR', 'KWD', 'BHD', 'OMR', 'ILS', 'EGP', 'MAD', 'NGN',
    'KES', 'ZAR', 'CNY', 'HKD', 'JPY', 'KRW', 'SGD', 'MYR', 'THB', 'IDR', 'PHP', 'VND', 'AUD', 'NZD',
    'CAD', 'MXN', 'BRL',
]
CURRENCIES = [
    (re.compile(r'(?<![a-z])USD(?![a-z])|US\$', re.IGNORECASE), 'USD'),
    (re.compile(r'(?<![a-su-z])EUR', re.IGNORECASE), 'EUR'),
    *[(_iso_code(iso), iso) for iso in ISO_CODES],
    (re.compile(r'€|euros?\b', re.IGNORECASE), 'EUR'),
    (re.compile(r'₹'), 'INR'),
    (re.compile(r'₨'), 'PKR'),
    (re.compile(r'\$|dollars?\b', re.IGNORECASE), 'USD'),
    (re.compile(r'£|pounds?\b', re.IGNORECASE), 'GBP'),
    (re.compile(r'franken|francs?\b|\bFr\.', re.IGNORECASE), 'CHF'),
    (re.compile(r'zł|zloty|złoty', re.IGNORECASE), 'PLN'),
]


def detect_currency(text):
    for pattern, code in CURRENCIES:
        if pattern.search(str(text or '')):
            return code
    return ''


# "Rs", "Rs." and "rupees" are used in Pakistan, India and Sri Lanka alike, and
# those rupees differ in value. A figure that names its currency only this way
# is not placed - taken as euros it would be about 300 times too large. The
# prompt asks for the ISO code (PKR, INR) to avoid this.
AMBIGUOUS_RUPEE = re.compile(r'(?<![a-z])rs\.?(?![a-z])|rupees?', re.IGNORECASE)


def _to_number(text):
    try:
        return float(text)
    except ValueError:
        return math.nan


def parse_number(raw):
    """
    "30.000.000", "30,000,000", "1,2", "1.5", "30 000 000" -> a number.

    A single separator followed by exactly three digits is a thousands separator
    ("30.000" is thirty thousand in German); anything else is a decimal point.
    """
    text = re.sub(r'\s', '', str(raw))
    commas = text.count(',')
    dots = text.count('.')

    if commas and dots:
        decimal = ',' if text.rfind(',') > text.rfind('.') else '.'
        thousands = '.' if decimal == ',' else ','
        return _to_number(text.replace(thousands, '').replace(decimal, '.', 1))

    if not commas and not dots:
        return _to_number(text)

    separator = ',' if commas else '.'
    parts = text.split(separator)
    if len(parts) > 2 or len(parts[1]) == 3:
        return _to_number(''.join(parts))
    return _to_number('.'.join(parts))


def _multiplier_of(suffix):
    if not suffix:
        return 0
    for pattern, multiplier in MULTIPLIERS:
        if pattern.fullmatch(suffix):
            return multiplier
    return 0


def _amounts(text):
    """Every amount in a piece of text, with where it sits and whether it had a multiplier."""
    found = []
    for match in AMOUNT.finditer(str(text)):
        value = parse_number(match.group(1))
        if not math.isfinite(value):
            continue
        found.append({
            'value': value,
            'multiplier': _multiplier_of(match.group(2) or match.group(3)),
            'start': match.start(),
            'end': match.end(),
        })
    return found


def _scaled(first, second=None):
    """"1-10M": the first number takes the multiplier the second one carries."""
    multiplier = first['multiplier'] or (second['multiplier'] if second else 0) or 1
    return first['value'] * multiplier


def parse_band(label):
    """
    A revenue band label -> {min, max, currency}, or None when the label is not
    a numeric band at all ("N/A", "Unknown").

    A single amount with no "<" or "+" ("10M EUR") is a point option: min and max
    are the same number, and a figure goes to the nearest one.
    """
    text = str(label or '')
    found = _amounts(text)
    currency = detect_currency(text)

    if len(found) == 2 and RANGE_JOIN.search(text[found[0]['end']:found[1]['start']]):
        low = _scaled(found[0], found[1])
        high = _scaled(found[1])
        return {'min': low, 'max': high, 'currency': currency} if high > low else None

    if len(found) == 1:
        amount = _scaled(found[0])
        before = text[:found[0]['start']]
        after = text[found[0]['end']:]

        if BELOW.search(before):
            return {'min': 0, 'max': amount, 'currency': currency}
        if PLUS_AFTER.search(after) or ABOVE.search(before):
            return {'min': amount, 'max': math.inf, 'currency': currency}
        if found[0]['multiplier'] or amount >= 10000:
            return {'min': amount, 'max': amount, 'currency': currency, 'point': True}

    return None


def parse_figure(text):
    """
    The researched figure -> {amount, currency, ambiguous}, or None.

    Brackets are dropped first, so "(2024)" is not read as two thousand euros. A
    range ("30-35 Mio. EUR") is placed by its midpoint. A bare number under ten
    thousand with no multiplier is skipped: "Umsatz 2023: 30 Mio. EUR" carries a
    year before the amount, and a lone "30" is a missing "million", not thirty
    euros.
    """
    plain = re.sub(r'\([^)]*\)', ' ', str(text or ''))
    found = _amounts(plain)

    for i, current in enumerate(found):
        following = found[i + 1] if i + 1 < len(found) else None
        is_range = bool(following) and bool(RANGE_JOIN.search(plain[current['end']:following['start']]))

        amount = (_scaled(current, following) + _scaled(following)) / 2 if is_range else _scaled(current)
        has_multiplier = current['multiplier'] or (is_range and following['multiplier'])

        if has_multiplier or amount >= 10000:
            currency = detect_currency(plain)
            return {
                'amount': amount,
                'currency': currency,
                'ambiguous': not currency and bool(AMBIGUOUS_RUPEE.search(plain)),
            }

    return None


def convert(amount, source, target, rates):
    """
    Converts between currencies with rates quoted per 1 EUR ({EUR: 1, USD: 1.08}).
    The same currency, or a side whose currency is unknown, passes through
    unchanged; a currency with no rate returns None rather than a guess.
    """
    if not source or not target or source == target:
        return amount
    source_rate = 1 if source == 'EUR' else (rates or {}).get(source)
    target_rate = 1 if target == 'EUR' else (rates or {}).get(target)
    if not source_rate or not target_rate:
        return None
    return (amount / source_rate) * target_rate


def band_for_figure(labels, figure_text, rates):
    """
    The band a figure falls into - or, when none contains it, the nearest one.

    The bands' currency is the first one any option names; options that name
    none share it. A figure with no currency of its own is taken to be in the
    board's currency already.

    `labels` is the column's options as [{index, label}]. Returns
    {index, label, amount, currency, from, original, nearest}, or {reason} when
    the figure cannot be placed, or None when there is no figure to place.
    """
    figure = parse_figure(figure_text)
    if not figure:
        return None
    if figure['ambiguous']:
        return {'reason': 'the currency is "Rs"/rupees with no ISO code (PKR, INR ...)'}

    bands = []
    for option in labels:
        band = parse_band(option['label'])
        if band:
            bands.append({**option, 'band': band})

    # One parsable band is a label that happens to hold a number, not a scale.
    if len(bands) < 2:
        return {'reason': 'the column options are not numeric bands'}

    currency = next((option['band']['currency'] for option in bands if option['band']['currency']), '')
    source = figure['currency'] or currency

    amount = convert(figure['amount'], source, currency, rates)
    if amount is None:
        return {'reason': f'no exchange rate for {source} -> {currency}'}

    # The band that contains the figure; otherwise the option nearest to it, so
    # a figure in a gap between bands, or between point options, still lands on
    # one of the column's own options. Ties go to the earlier option.
    #
    # Containment is checked first: exactly 10M sits inside "10M-50M" and only
    # touches "1M-10M" at its excluded upper bound, where the distance is also 0.
    hit = next((option for option in bands if _contains(option['band'], amount)), None)
    nearest = hit is None
    if nearest:
        hit = min(bands, key=lambda option: _distance_to(amount, option['band']))

    return {
        'index': hit['index'],
        'label': hit['label'],
        'amount': amount,
        'currency': currency,
        'from': source,
        'original': figure['amount'],
        'nearest': nearest,
    }


def _contains(band, amount):
    """Lower bound in, upper bound out; a point option only holds its own value."""
    if band.get('point'):
        return amount == band['min']
    return band['min'] <= amount < band['max']


def _distance_to(amount, band):
    """0 inside the band (lower bound in, upper bound out), else how far outside it."""
    if band.get('point'):
        return abs(amount - band['min'])
    if amount < band['min']:
        return band['min'] - amount
    if amount >= band['max']:
        return amount - band['max']
    return 0


def format_amount(amount, currency=''):
    """32400000 -> "32.4M USD", for Comments and the run log."""
    if amount >= 1e9:
        divisor, suffix = 1e9, 'B'
    elif amount >= 1e6:
        divisor, suffix = 1e6, 'M'
    elif amount >= 1e3:
        divisor, suffix = 1e3, 'K'
    else:
        divisor, suffix = 1, ''

    # Two decimals, rounded half up, without trailing zeros: 30 -> "30", 56.25 -> "56.25".
    value = Decimal(amount / divisor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP).normalize()
    text = f'{value:f}'
    return f"{text}{suffix}{f' {currency}' if currency else ''}"
