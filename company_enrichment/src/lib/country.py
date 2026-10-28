"""
Classifies the lead's country from what the user entered, BEFORE the research.

The research is then scoped to that one country, so a same-named company
abroad cannot be found instead. The cheap, certain signals are tried here in
code; only an address none of them can place goes to the model
(`classify_country` in services/openai.py), which reads the city, postal code
format and region.

Country names come from Babel's CLDR data rather than a hand-kept list, in the
languages an address on these boards is written in - so "Deutschland",
"Österreich", "Schweiz", "Nederland" and "Germany" are all recognised for every
country.
"""
import re
import string
import unicodedata

import regex
from babel import Locale

LANGUAGES = ['en', 'de', 'fr', 'it', 'es', 'nl', 'pl', 'pt', 'cs', 'da', 'sv']

# Region codes that are not countries - and historical ones CLDR still names,
# or "Deutschland" would classify as DD, East Germany.
NOT_COUNTRIES = {
    'AC', 'CP', 'DG', 'EA', 'EU', 'EZ', 'IC', 'QO', 'TA', 'UN', 'XA', 'XB', 'ZZ',
    'AN', 'BU', 'CS', 'DD', 'FX', 'NT', 'SU', 'TP', 'YU', 'ZR',
}

_ENGLISH_NAMES = Locale.parse('en').territories


def _fold(value):
    text = unicodedata.normalize('NFD', str(value or ''))
    text = re.sub('[̀-ͯ]', '', text).lower().replace('ß', 'ss')
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def _build_by_name():
    """Folded country name, in any of LANGUAGES -> ISO code."""
    by_name = {}
    displays = [Locale.parse(language).territories for language in LANGUAGES]

    for a in string.ascii_uppercase:
        for b in string.ascii_uppercase:
            code = a + b
            if code in NOT_COUNTRIES:
                continue
            for display in displays:
                name = display.get(code)
                if name and name != code and _fold(name) not in by_name:
                    by_name[_fold(name)] = code

    # Everyday forms CLDR does not use.
    for name, code in [('usa', 'US'), ('uk', 'GB'), ('england', 'GB'), ('holland', 'NL'), ('brd', 'DE')]:
        by_name[name] = code
    return by_name


BY_NAME = _build_by_name()

# "D-71336", "A-1010", "CH-8000" - the old European vehicle-code postal prefix.
POSTAL_PREFIX = {
    'D': 'DE', 'A': 'AT', 'CH': 'CH', 'F': 'FR', 'I': 'IT', 'NL': 'NL', 'B': 'BE', 'L': 'LU',
    'PL': 'PL', 'CZ': 'CZ', 'DK': 'DK', 'S': 'SE', 'E': 'ES', 'P': 'PT', 'FL': 'LI', 'H': 'HU',
}
POSTAL_PREFIX_RE = regex.compile(r'(?<![\p{L}\d])(CH|NL|PL|CZ|DK|FL|D|A|F|I|B|L|S|E|P|H)\s?-\s?\d{4,5}(?!\d)')


def country_name(code):
    if not re.fullmatch(r'[A-Z]{2}', code or ''):
        return ''
    return _ENGLISH_NAMES.get(code, code)


def country_code(value):
    """A country name or ISO code as a whole value: "Germany", "Deutschland", "DE"."""
    folded = _fold(value)
    if not folded:
        return ''
    if folded in BY_NAME:
        return BY_NAME[folded]

    code = str(value).strip().upper()
    if re.fullmatch(r'[A-Z]{2}', code) and code not in NOT_COUNTRIES and country_name(code) != code:
        return code
    return ''


def country_from_input(country_column, address):
    """
    The country the user's input names, or None when it names none.

    An address is only read at the places a country actually sits - a whole
    comma segment, or the words the address ends on - so "Schweizer Straße" or
    "Georgia Allee" in the street cannot classify a lead.

    Returns {'code', 'name', 'source'} or None.
    """
    def found(code, source):
        return {'code': code, 'name': country_name(code), 'source': source}

    from_column = country_code(country_column)
    if from_column:
        return found(from_column, 'Country column')

    segments = [segment.strip() for segment in str(address or '').split(',') if segment.strip()]
    for segment in reversed(segments):
        words = re.split(r'\s+', re.sub(r'\d+', ' ', segment).strip())
        # The segment itself, then its last one to three words ("1010 Wien Österreich").
        for take in [len(words), 3, 2, 1]:
            if take > len(words):
                continue
            code = BY_NAME.get(_fold(' '.join(words[-take:])))
            if code:
                return found(code, 'country name in address')

    prefix = POSTAL_PREFIX_RE.search(str(address or ''))
    if prefix:
        return found(POSTAL_PREFIX[prefix.group(1)], 'postal prefix in address')

    return None
