"""
The comparisons Vendor Search makes without the AI:

  same_product      "iPhone" = "iphone" = " iPhone ", but "iPhone 15" is another product
  Existing          the vendors already on the board for a product, and whether a candidate repeats one
  germany_problem   why a vendor fails the Germany rule, or None when it passes
"""
import re
import unicodedata
from urllib.parse import urlsplit

from . import settings

# Legal forms are dropped before comparing names, so "Tech World GmbH" repeats "Tech World".
LEGAL_FORMS = re.compile(
    r'\b(gmbh\s*&\s*co\.?\s*kgaa|gmbh\s*&\s*co\.?\s*kg|ag\s*&\s*co\.?\s*kg|ug\s*\(haftungsbeschrankt\)|'
    r'gmbh|mbh|ag|kgaa|kg|ohg|gbr|ug|e\.?\s?k\.?|e\.?\s?v\.?|se|ltd|limited|inc|llc|co)(?!\w)\.?'
)

# A 5-digit German postal code, not part of a longer number.
POSTAL_CODE = re.compile(r'(?<!\d)\d{5}(?!\d)')

# Places an address must not name for a vendor that is based in Germany.
FOREIGN_MARKERS = re.compile(
    r'\b(osterreich|austria|schweiz|switzerland|suisse|svizzera|liechtenstein|nederland|netherlands|'
    r'belgien|belgium|frankreich|france|italien|italy|polen|poland|tschechien|czech|danemark|denmark|'
    r'luxemburg|luxembourg|united kingdom|england|usa|united states|china|hong kong|taiwan)\b'
)


def _fold(text):
    """Lower case, no accents (ü -> u, ß -> ss), single spaces."""
    text = unicodedata.normalize('NFKD', str(text or '')).replace('ß', 'ss')
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', text).strip().casefold()


def product_key(product):
    """
    The key two requests share when they write the same product the same way, apart from case,
    accents, spaces and punctuation: "Euro pallets", "europallets" and "Euro-Pallets" -> "europallets".
    Typos, plurals and translations are left to the AI check (research.match_product).
    """
    return re.sub(r'[^a-z0-9]', '', _fold(product))


def same_product(a, b):
    return bool(product_key(a)) and product_key(a) == product_key(b)


def company_key(name):
    """'Tech-World GmbH & Co. KG' -> 'tech world'."""
    folded = _fold(name).replace('&', ' & ')
    folded = LEGAL_FORMS.sub(' ', folded)
    folded = re.sub(r'[^a-z0-9]+', ' ', folded)
    return re.sub(r'\s+', ' ', folded).strip()


def domain_of(url):
    """'https://www.Tech-World.de/shop?x=1' -> 'tech-world.de'. '' when there is no host."""
    text = str(url or '').strip()
    if not text:
        return ''
    if '://' not in text:
        text = 'https://' + text
    try:
        host = urlsplit(text).hostname or ''
    except ValueError:
        return ''
    host = host.lower().rstrip('.')
    host = host[4:] if host.startswith('www.') else host
    return host if '.' in host else ''


def _as_names(names):
    return [names] if names is None or isinstance(names, str) else list(names)


class Existing:
    """
    The vendors already known for one product: from the board, then the ones this run adds.

    A vendor is known by its company names (legal and trading) and its website.
    The bot names a vendor row after the product it was found for, so the row
    name only counts as the company on rows without a Legal Company Name (rows
    added by hand).
    """

    def __init__(self, vendors=()):
        self.names = set()
        self.domains = set()
        self.display = []
        for vendor in vendors:
            legal_name = vendor.get('legal_name')
            self.add([legal_name] if legal_name else [vendor.get('name')], vendor.get('website'))

    def add(self, names, website=''):
        names = [str(name) for name in _as_names(names) if name]
        domain = domain_of(website)
        self.names.update(key for key in map(company_key, names) if key)
        if domain:
            self.domains.add(domain)
        if names or domain:
            self.display.append({'name': names[0] if names else '', 'website': domain})

    def repeats(self, names, website=''):
        keys = [company_key(name) for name in _as_names(names) if name]
        domain = domain_of(website)
        return any(key and key in self.names for key in keys) or bool(domain and domain in self.domains)


def is_german_postal_code(text):
    return bool(POSTAL_CODE.search(str(text or '')))


def _is_url(value):
    return bool(re.match(r'^https?://[^\s/.]+\.[^\s]{2,}$', str(value or '').strip(), re.IGNORECASE))


def _is_area(value):
    folded = _fold(value)
    return folded in (_fold(settings.SEARCH_AREA), _fold(settings.SEARCH_AREA_CODE), 'deutschland', 'germany', 'de')


def candidate_problem(candidate):
    """Step 1's cheap check: a candidate that is plainly not in Germany is not worth a deep check."""
    if not str(candidate.get('name') or '').strip():
        return 'no company name'
    country = candidate.get('country')
    if country and not _is_area(country):
        return f'country is {country}'
    postal = candidate.get('postal_code')
    if postal and not is_german_postal_code(postal):
        return f'postal code {postal} is not German'
    return None


def germany_problem(vendor):
    """
    Why a deep-checked vendor fails the Germany rule, or None when it passes.

    Decided here, not by the model: the model's yes is required, and so is a
    German address with a 5-digit postal code and a city, confirmed from a source
    URL (Impressum or register). Delivering to Germany is not enough.
    """
    if vendor.get('based_in_germany') is not True:
        return 'not confirmed as based in Germany'
    if not _is_area(vendor.get('country_code') or vendor.get('country')):
        return f"country is {vendor.get('country_code') or vendor.get('country') or 'missing'}"

    address = str(vendor.get('complete_address') or '').strip()
    postal = str(vendor.get('postal_code') or '').strip()
    city = str(vendor.get('city') or '').strip()
    if not address or not city:
        return 'no full address'
    if not is_german_postal_code(postal or address):
        return 'no German postal code'
    if FOREIGN_MARKERS.search(_fold(address)):
        return 'address is outside Germany'
    if not _is_url(vendor.get('address_source_url')):
        return 'address has no source'
    return None


def product_problem(vendor):
    """A vendor must clearly sell this exact product, with a page that shows it."""
    if vendor.get('sells_exact_product') is not True:
        return 'does not clearly sell this exact product'
    if not _is_url(vendor.get('product_evidence_url')):
        return 'no page showing the product'
    return None
