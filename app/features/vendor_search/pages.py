"""
The product page check: the page the AI names as proof must exist, be on the
company's own website, and mention the product.

A smaller model sometimes invents a product - for "zzqlorp 8812" it described a
real company's "zzqlorp 8812 fuel pump". The code opens the page itself:

  product page on another website (a marketplace)        -> rejected
  host does not exist, or the page is 404 / 410           -> rejected
  page text has neither the request's words nor the
  word(s) the AI says the page uses for the product       -> rejected
  blocked (403 / 429 / 5xx), timeout, or a page with
  almost no text (built by JavaScript)                    -> cannot tell: not rejected

product_page_problem() returns why a vendor fails, or None.
"""
import html
import re
from urllib.parse import urljoin, urlsplit

import requests

from .matching import _fold, domain_of

TIMEOUT_SECONDS = 10
MAX_BYTES = 3_000_000
# Below this much visible text the page is built by JavaScript and cannot be read here.
MIN_TEXT = 400
MISSING = {404, 410}
# A generic client name - nothing about the user or the project is sent.
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; VendorSearch/1.0)', 'Accept-Language': 'de,en;q=0.8'}
# Second-level names that are part of a public suffix ("example.co.uk").
SUFFIX_PARTS = {'co', 'com', 'org', 'net', 'gov', 'ac'}


def fetch(url):
    """(HTTP status, page text). Raises requests.RequestException when the page cannot be reached."""
    res = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS, allow_redirects=True, stream=True)
    try:
        body = res.raw.read(MAX_BYTES, decode_content=True) or b''
    finally:
        res.close()
    return res.status_code, body.decode(res.encoding or 'utf-8', errors='replace')


def open_link(url):
    """(HTTP status, the address it ended on after redirects) - without reading the body (a PDF can be large)."""
    res = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS, allow_redirects=True, stream=True)
    res.close()
    return res.status_code, res.url


def catalogue_exists(url):
    """
    The catalogue link really opens. Strict, unlike the product page check: an
    invented link (the AI wrote ".../produktkatalog.pdf" for three vendors, all 404)
    must never reach the board. 404, blocked, timeout, an unknown host, or a
    redirect to the home page - all count as no catalogue.
    """
    try:
        status, final = open_link(url)
    except requests.RequestException:
        return False
    if status >= 400:
        return False
    asked, landed = urlsplit(url).path.strip('/'), urlsplit(str(final or url)).path.strip('/')
    return not (asked and not landed)


# Words that name a catalogue in a link's address or text (folded: umlauts become plain letters).
CATALOGUE_WORDS = ('katalog', 'catalog', 'broschure', 'brochure', 'prospekt')
LINK = re.compile(r'<a\b[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
MAX_CATALOGUE_LINKS = 5


def catalogue_links(website, markup):
    """
    The catalogue links on a page of the vendor's website, best first: a link whose
    address or text names a catalogue ("Gesamtkatalog 2026", "Broschüre", ...), on the
    vendor's own site, PDFs before pages. Not opened here.
    """
    site = site_name(website)
    found = []
    for href, label in LINK.findall(markup or ''):
        if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        link = urljoin(website, html.unescape(href.strip()))
        if not link.startswith(('http://', 'https://')) or site_name(link) != site:
            continue
        words = _fold(html.unescape(link + ' ' + re.sub(r'<[^>]+>', ' ', label)))
        if any(word in words for word in CATALOGUE_WORDS) and link not in found:
            found.append(link)
    return sorted(found, key=lambda link: not urlsplit(link).path.lower().endswith('.pdf'))


def find_catalogue(website):
    """
    A catalogue linked on the vendor's home page that really opens, or None. Free: one
    page load, no AI - it found Sitwell's "Gesamtkatalog 2026/27" PDF that the AI missed.
    """
    try:
        status, markup = fetch(website)
    except requests.RequestException:
        return None
    if status >= 400:
        return None
    for link in catalogue_links(website, markup)[:MAX_CATALOGUE_LINKS]:
        if catalogue_exists(link):
            return link
    return None


def site_name(url):
    """The name a company's domains share: www.bbraun.de and bbraun.com -> "bbraun"."""
    parts = domain_of(url).split('.')
    if len(parts) < 2:
        return ''
    if len(parts) > 2 and parts[-2] in SUFFIX_PARTS:
        return parts[-3]
    return parts[-2]


def page_text(markup):
    """The visible words of an HTML page, folded like every other comparison here."""
    text = re.sub(r'(?is)<(script|style|noscript)\b.*?</\1>', ' ', str(markup or ''))
    text = re.sub(r'(?s)<[^>]+>', ' ', text)
    return _fold(html.unescape(text))


def _words(term):
    return [word for word in re.findall(r'[a-z0-9]+', _fold(term)) if len(word) >= 3]


def mentions(text, term):
    """The term is on the page: as a whole, or every word of it (3+ letters) somewhere."""
    folded = _fold(term)
    if not folded:
        return False
    if folded in text:
        return True
    words = _words(term)
    return bool(words) and all(word in text for word in words)


def product_terms(vendor, product):
    terms = [product]
    found = vendor.get('product_terms')
    if isinstance(found, str):
        found = [found]
    for term in found or []:
        if isinstance(term, str) and 0 < len(term.strip()) <= 80:
            terms.append(term.strip())
    return terms


def product_page_problem(vendor, product):
    url = str(vendor.get('product_evidence_url') or '').strip()
    website = vendor.get('website')
    if website and site_name(url) and site_name(url) != site_name(website):
        return f'product page is not on the company website ({domain_of(url)})'

    try:
        status, markup = fetch(url)
    except requests.Timeout:
        return None
    except requests.ConnectionError:
        return f'product page cannot be reached ({domain_of(url) or url})'
    except requests.RequestException:
        return None

    if status in MISSING:
        return f'product page does not exist (HTTP {status})'
    if status >= 400:
        return None

    text = page_text(markup)
    if len(text) < MIN_TEXT:
        return None
    if any(mentions(text, term) for term in product_terms(vendor, product)):
        return None
    return 'product page does not mention the product'
