"""
A checked vendor -> the column_values of its new item.

Every value is validated before it is sent. A value that is missing or not
valid is left out - never guessed, never a placeholder. ("N/A" in an email
column is what made monday reject Company Enrichment's whole write.)
"""
import datetime
import re

from . import settings
from .matching import _fold, domain_of

EMAIL = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$')
URL = re.compile(r'^https?://[^\s/.]+\.[^\s]{2,}$', re.IGNORECASE)
VAT = re.compile(r'^DE\d{9}$')
# "50-200", "50 – 200", "50 bis 200", "50 to 200": a range is not one number.
RANGE = re.compile(r'\d\s*(-|–|—|bis|to)\s*\d', re.IGNORECASE)

MAX_TEXT = 250
MAX_DESCRIPTION = 2000
MAX_CERTIFICATIONS = 10

NOT_FOUND = {'', 'n/a', 'na', 'none', 'null', 'unknown', 'not found', 'nicht gefunden', 'not available', '-'}

VENDOR_TYPE_WORDS = {
    'Manufacturer': ('manufacturer', 'hersteller', 'producer', 'produzent', 'fabrikant', 'oem'),
    'Distributor': ('distributor', 'distribution', 'wholesaler', 'wholesale', 'grosshandel', 'grosshandler',
                    'grosshaendler', 'vertrieb', 'importer', 'importeur'),
    'Reseller': ('reseller', 'retailer', 'retail', 'dealer', 'handler', 'haendler', 'shop', 'store',
                 'einzelhandel', 'fachhandel', 'fachhandler'),
}

REGION_ALIASES = {
    'bundesweit': settings.NATIONWIDE, 'deutschlandweit': settings.NATIONWIDE, 'nationwide': settings.NATIONWIDE,
    'germany wide': settings.NATIONWIDE, 'germany-wide': settings.NATIONWIDE, 'all of germany': settings.NATIONWIDE,
    'germany': settings.NATIONWIDE, 'deutschland': settings.NATIONWIDE, 'ganz deutschland': settings.NATIONWIDE,
    'bavaria': 'Bayern', 'hesse': 'Hessen', 'lower saxony': 'Niedersachsen',
    'north rhine-westphalia': 'Nordrhein-Westfalen', 'north rhine westphalia': 'Nordrhein-Westfalen',
    'nrw': 'Nordrhein-Westfalen', 'rhineland-palatinate': 'Rheinland-Pfalz', 'rhineland palatinate': 'Rheinland-Pfalz',
    'saxony': 'Sachsen', 'saxony-anhalt': 'Sachsen-Anhalt', 'saxony anhalt': 'Sachsen-Anhalt',
    'thuringia': 'Thüringen', 'mecklenburg-western pomerania': 'Mecklenburg-Vorpommern',
    'mecklenburg western pomerania': 'Mecklenburg-Vorpommern',
    **{_fold(state): state for state in settings.STATES},
}


def clean(value):
    """The value as a trimmed string, or '' when it is empty or a 'not found' answer."""
    if value is None or isinstance(value, (dict, list)):
        return ''
    text = re.sub(r'\s+', ' ', str(value)).strip()
    return '' if text.casefold().strip('. ') in NOT_FOUND else text


def text(value, limit=MAX_TEXT):
    return clean(value)[:limit]


def email(value):
    address = clean(value).removeprefix('mailto:')
    return address if EMAIL.match(address) else ''


def url(value):
    link = clean(value)
    if link and not link.lower().startswith(('http://', 'https://')):
        link = 'https://' + link.lstrip('/')
    return link if URL.match(link) and domain_of(link) else ''


def linkedin(value):
    link = url(value)
    return link if 'linkedin.com/' in link.lower() else ''


def vat_id(value):
    vat = re.sub(r'[\s.\-]', '', clean(value)).upper()
    return vat if VAT.match(vat) else ''


def phone(value):
    """A German number as +49…, or '' - a foreign or too-short number is not written."""
    raw = clean(value)
    if not raw:
        return ''
    number = re.sub(r'\(0\)', '', raw)
    number = re.sub(r'[^\d+]', '', number)
    if number.startswith('00'):
        number = '+' + number[2:]
    elif number.startswith('0'):
        number = settings.SEARCH_AREA_DIALLING_CODE + number[1:]
    if not number.startswith(settings.SEARCH_AREA_DIALLING_CODE):
        return ''
    digits = number[len(settings.SEARCH_AREA_DIALLING_CODE):]
    return number if 6 <= len(digits) <= 13 and digits.isdigit() else ''


def whole_number(value):
    """'1.200', '1,200', 'ca. 250', 250 -> the number. A range or anything vaguer -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value > 0 and value.is_integer() else None
    raw = clean(value)
    if not raw or RANGE.search(raw):
        return None
    numbers = re.findall(r'\d{1,3}(?:[.,\s]\d{3})+|\d+', raw)
    if len(numbers) != 1:
        return None
    number = int(re.sub(r'\D', '', numbers[0]))
    return number if number > 0 else None


def year_founded(value):
    year = whole_number(value)
    return year if year and 1700 <= year <= datetime.date.today().year else None


def employees(value):
    return whole_number(value)


def vendor_type(value):
    folded = _fold(clean(value))
    if not folded:
        return ''
    for label in settings.VENDOR_TYPES:
        if folded == label.casefold():
            return label
    for label, words in VENDOR_TYPE_WORDS.items():
        if any(re.search(rf'\b{re.escape(word)}\b', folded) for word in words):
            return label
    return ''


def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return re.split(r'[;,\n]', value)
    return []


def regions(value):
    """Only labels from settings.REGIONS. 'Bundesweit' covers every state, so it stands alone."""
    found = []
    for entry in _as_list(value):
        label = REGION_ALIASES.get(_fold(clean(entry)))
        if label and label not in found:
            found.append(label)
    return [settings.NATIONWIDE] if settings.NATIONWIDE in found else found


def certifications(value):
    found = []
    for entry in _as_list(value):
        label = text(entry, 60)
        if label and label.casefold() not in (f.casefold() for f in found):
            found.append(label)
    return found[:MAX_CERTIFICATIONS]


def item_name(vendor):
    return text(vendor.get('company_name'), 255) or text(vendor.get('legal_name'), 255)


def column_values(vendor, product_label):
    """The new vendor item's column_values. Search Source, product and country are always there."""
    values = {
        settings.SEARCH_SOURCE: {'label': settings.RESEARCH_COMPLETED},
        settings.PRODUCT_CATEGORIES: {'labels': [product_label]},
        settings.COUNTRY: {'countryCode': settings.SEARCH_AREA_CODE, 'countryName': settings.SEARCH_AREA},
    }

    def put(column, value):
        if value not in ('', None, []):
            values[column] = value

    put(settings.LEGAL_NAME, text(vendor.get('legal_name')))
    put(settings.COMPLETE_ADDRESS, text(vendor.get('complete_address')))
    put(settings.VAT_ID, vat_id(vendor.get('vat_id')))

    year = year_founded(vendor.get('year_founded'))
    put(settings.YEAR_FOUNDED, str(year) if year else '')
    size = employees(vendor.get('employees'))
    put(settings.COMPANY_SIZE, str(size) if size else '')

    description = text(vendor.get('description'), MAX_DESCRIPTION)
    put(settings.DESCRIPTION, {'text': description} if description else '')

    website = url(vendor.get('website'))
    put(settings.WEBSITE, {'url': website, 'text': domain_of(website)} if website else '')
    profile = linkedin(vendor.get('linkedin'))
    put(settings.LINKEDIN, {'url': profile, 'text': 'LinkedIn'} if profile else '')

    address = email(vendor.get('company_email'))
    put(settings.COMPANY_EMAIL, {'email': address, 'text': address} if address else '')

    for column, key in ((settings.COMPANY_PHONE, 'company_phone'), (settings.CONTACT_PHONE, 'contact_person_phone')):
        number = phone(vendor.get(key))
        put(column, {'phone': number, 'countryShortName': settings.SEARCH_AREA_CODE} if number else '')

    put(settings.CONTACT_PERSON, text(vendor.get('contact_person'), 120))

    kind = vendor_type(vendor.get('vendor_type'))
    put(settings.VENDOR_TYPE, {'label': kind} if kind else '')

    region_labels = regions(vendor.get('delivery_regions'))
    put(settings.DELIVERY_REGIONS, {'labels': region_labels} if region_labels else '')
    certificates = certifications(vendor.get('certifications'))
    put(settings.CERTIFICATIONS, {'labels': certificates} if certificates else '')

    return values
