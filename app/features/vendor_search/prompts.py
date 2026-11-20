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


def job_title_prompt(roles, titles):
    asked = '\n'.join(f'- {json.dumps(role, ensure_ascii=False)}' for role in roles)
    listed = '\n'.join(f'- {json.dumps(title, ensure_ascii=False)}' for title in titles)
    return f"""Match each job title of a company contact to the one title from our list that means the same job.

JOB TITLES (as published by the company, any language):
{asked}

OUR LIST:
{listed}

Rules:
- Pick only a title from our list, copied exactly as listed.
- The same job in another language counts: "Managing Director", "CEO" and "Inhaber" are "Geschäftsführer"; "Head of Sales" is "Vertriebsleiter".
- If no title on our list means the same job, use null. Do not guess.

Answer with JSON only, one entry per job title:
{{"matches": {{"<job title>": "<title from our list, or null>"}}}}"""


def find_prompt(product, existing, limit=settings.MAX_CANDIDATES):
    area = settings.SEARCH_AREA
    return f"""You are a procurement researcher. Find companies based in {area} that sell this exact product:

PRODUCT: {product}

RULES
1. Location: only companies whose headquarters or registered office is in {area}, with a {area} address in their Impressum. A company located outside {area} is NOT allowed, even if it delivers to {area} or has a .de website.
2. Exact product: they must clearly sell "{product}" itself - not only the general category. Find a page on their website (product page, catalogue, shop) that shows it.
3. Prefer manufacturers and official / authorised distributors over small resellers.
4. Prefer established companies with an active website.
5. Do NOT include these companies - they are already on our list for this product, or were already checked:
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
4. Confirm it sells exactly "{product}" (not only the general category): give the URL of a page ON THE COMPANY'S OWN WEBSITE that shows it, and the exact word(s) that page uses for the product (often German, e.g. "Industriereiniger").
5. LinkedIn: search for "site:linkedin.com/company" together with the company name, and give the company page URL.
6. Employees: look on the LinkedIn company page ("Company size" / "Unternehmensgröße"), northdata.de, the company website ("Über uns", "Unternehmen", "Karriere") and press articles.
7. Also find: year founded, a general company email and phone, a named contact person (sales / purchasing / managing director) with their direct phone if published, the regions in {area} it delivers to, and its certifications (e.g. ISO 9001).
8. VAT IDs in {area} start with "DE" followed by 9 digits.

STRICT RULES
- Only facts you found in a source. If you cannot find a value, use null. Never guess or estimate.
- If you cannot find a page on the company's website that shows this exact product, set sells_exact_product to false. Never describe a product the company does not list.
- employees: copy the employee number, or the range if only a range is published, exactly as the source states it, and give that page in employees_source_url. Never write a number you did not read in a source for THIS company.
- The JSON below shows only the format. Do not copy anything from it.
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
  "product_evidence_url": "https://... page on the company's website showing {product}",
  "product_terms": ["the word(s) that page uses for the product"],
  "vat_id": "the VAT ID from the Impressum, or null",
  "year_founded": "the year from a source, or null",
  "employees": "the employee number or range from the source, or null",
  "employees_source_url": "https://... the page that states the employee count, or null",
  "description": "2-3 sentences: what the company does and how it relates to {product}",
  "website": "https://...",
  "linkedin": "https://www.linkedin.com/company/... or null",
  "company_email": "general email or null",
  "company_phone": "phone or null",
  "contact_person": "the contact's full name only, without the job title, or null",
  "contact_person_role": "the contact's job title as published (e.g. Geschäftsführer, Head of Sales), or null",
  "contact_person_phone": "phone or null",
  "vendor_type": "Manufacturer | Distributor | Reseller | null",
  "delivery_regions": ["..."],
  "certifications": ["..."]}}"""
