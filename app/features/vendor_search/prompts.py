"""
The two research prompts.

  find_prompt   step 1: a list of candidate vendors for the product (cheap, broad)
  check_prompt  step 2: one candidate, verified in depth (the Company Enrichment way:
                Impressum, Handelsregister, company website)

Both ask for JSON only, so research.py can read the answer without guessing.
"""
import json

from . import settings


def _known_vendors(existing):
    if not existing:
        return 'None yet.'
    return '\n'.join(f"- {v['name']}" + (f" ({v['website']})" if v.get('website') else '') for v in existing)


def match_prompt(product, labels):
    listed = '\n'.join(f'- {json.dumps(label, ensure_ascii=False)}' for label in labels)
    return f"""A buyer asked for this product: {json.dumps(product, ensure_ascii=False)}

These products are already on our vendor board:
{listed}

Which of them are the SAME product as the request, only written differently - a typo, another spelling, singular or plural, with or without spaces or hyphens, German or English, or a common abbreviation? For example "eurppallets", "Europaletten" and "Euro pallet" are the same product as "Euro pallets".

They are NOT the same if they differ in model, version, size, material or variant, or if one is a broader or narrower category. For example "iPhone 15" is not "iPhone", "Latex gloves" is not "Nitrile gloves", and "Pallets" is not "Euro pallets".

Answer with JSON only, copying the names exactly as listed, or an empty list if none is the same product:
{{"matches": ["..."]}}"""


def find_prompt(product, existing, limit=settings.MAX_CANDIDATES):
    area = settings.SEARCH_AREA
    return f"""You are a procurement researcher. Find companies based in {area} that sell this exact product:

PRODUCT: {product}

RULES
1. Location: only companies whose headquarters or registered office is in {area}, with a {area} address in their Impressum. A company located outside {area} is NOT allowed, even if it delivers to {area} or has a .de website.
2. Exact product: they must clearly sell "{product}" itself - not only the general category. Find a page on their website (product page, catalogue, shop) that shows it.
3. Prefer manufacturers and official / authorised distributors over small resellers.
4. Prefer established companies with an active website.
5. Do NOT include these companies - they are already on our list for this product:
{_known_vendors(existing)}
6. Do not invent companies, websites or addresses. Only list companies you found in your web search. If you find fewer than {limit}, list only those.

Search the web (company websites, Impressum pages, manufacturer and distributor directories, wlw.de, industry portals). Return up to {limit} companies, best first.

Answer with JSON only, no other text:
{{"candidates": [
  {{"name": "company name",
    "website": "https://...",
    "city": "city",
    "postal_code": "5-digit postal code",
    "country": "{area}",
    "vendor_type": "Manufacturer | Distributor | Reseller",
    "product_evidence_url": "https://... page showing they sell {product}",
    "why": "one sentence"}}
]}}"""


def check_prompt(product, candidate):
    area = settings.SEARCH_AREA
    regions = ', '.join(settings.REGIONS)
    known = json.dumps(
        {key: candidate.get(key) for key in ('name', 'website', 'city', 'postal_code') if candidate.get(key)},
        ensure_ascii=False,
    )
    return f"""Verify this company in depth as a vendor for the product "{product}". Use web search.

COMPANY (from an earlier search, may contain errors): {known}

STEPS
1. Find the company's official website and its Impressum page. Read the legal name, full address, VAT ID (USt-IdNr.), register entry, email and phone from the Impressum.
2. Confirm the legal name and address in the company register: handelsregister.de, unternehmensregister.de or northdata.de.
3. Confirm the company is based in {area}: its registered office / headquarters must have a {area} address with a 5-digit postal code. A company located outside {area} does not qualify, even if it delivers to {area}.
4. Confirm it sells exactly "{product}" (not only the general category): give the URL of a page that shows it.
5. Find: year founded, number of employees, LinkedIn company page, a general company email and phone, a named contact person (sales / purchasing / managing director) with their direct phone if published, the regions in {area} it delivers to, and its certifications (e.g. ISO 9001).
6. VAT IDs in {area} start with "DE" followed by 9 digits.

STRICT RULES
- Only facts you found in a source. If you cannot find a value, use null. Never guess or estimate.
- employees: a single number from a source. If only a range is published (e.g. "50-200"), use null.
- vendor_type: exactly one of "Manufacturer", "Distributor", "Reseller", or null.
- delivery_regions: labels from this list only: {regions}. Use "{settings.NATIONWIDE}" if they deliver to all of {area}.

Answer with JSON only, no other text:
{{"company_name": "short trading name",
  "legal_name": "legal name with legal form, from the Impressum or register",
  "complete_address": "street and number, postal code city, {area}",
  "postal_code": "5 digits",
  "city": "city",
  "country_code": "ISO code, e.g. DE",
  "based_in_germany": true or false,
  "address_source_url": "https://... Impressum or register page with this address",
  "sells_exact_product": true or false,
  "product_evidence_url": "https://... page showing {product}",
  "vat_id": "DE123456789 or null",
  "year_founded": 1990 or null,
  "employees": 250 or null,
  "description": "2-3 sentences: what the company does and how it relates to {product}",
  "website": "https://...",
  "linkedin": "https://www.linkedin.com/company/... or null",
  "company_email": "general email or null",
  "company_phone": "phone or null",
  "contact_person": "name and role, or null",
  "contact_person_phone": "phone or null",
  "vendor_type": "Manufacturer | Distributor | Reseller | null",
  "delivery_regions": ["..."],
  "certifications": ["..."]}}"""
