"""
Everything Vendor Search is configured with, in one place.

SEARCH_AREA is the one switch for where vendors may be based. The prompts, the
Germany check in matching.py and the Country column all read it from here.
"""
from app.core.config import setting

# ---- Where vendors may be based -------------------------------------------------
SEARCH_AREA = 'Germany'
SEARCH_AREA_CODE = 'DE'
SEARCH_AREA_DIALLING_CODE = '+49'

# ---- The boards this block runs on ----------------------------------------------
# The column ids below are this board's. A new board (e.g. production) is added
# here only after its column ids have been checked against these.
BOARDS = {
    5107912125: 'Vendor Mining Board (Dev Sandbox)',
}

# Group "1. Vendor Search in Progress": requests are created here. Only items here are searched.
REQUEST_GROUP_ID = 'topics'
# Group "2. Criteria Check & ICP Scoring": the 2nd and 3rd vendors are created in group 1
# and then moved here, so the board's "item moves to group 2" automation runs for them
# as it does for the request. The request (filled with the best vendor) is never moved
# by the code - the board's own automation decides that.
DONE_GROUP_ID = 'new_group'

# ---- Columns (Vendor Mining Board) ----------------------------------------------
SEARCH_SOURCE = 'color_mm95j9rp'
# "Name of Product" (text): the product a vendor was found for. Replaced the dropdown
# dropdown_mm9512qn on 2026-11-24, which grew one new label with every search.
PRODUCT_NAME = 'text_mm9dq3g3'
# "Product Catagory From Purchase Requirement" (dropdown): set on the request from the
# purchase requirement. The 2nd and 3rd vendors get the request's labels copied.
PRODUCT_CATEGORY = 'dropdown_mm9cm8vk'
# A category the AI names when none of the column's options fits (e.g. "Sports & Leisure")
# is created as a new option - at most this long, and reused by later searches.
MAX_CATEGORY_LENGTH = 40
COUNTRY = 'country_mm95yne6'
LEGAL_NAME = 'text_mm96vz3j'
COMPLETE_ADDRESS = 'text_mm96j9a1'
VAT_ID = 'text_mm96mq88'
YEAR_FOUNDED = 'numeric_mm965zaj'
COMPANY_SIZE = 'numeric_mm96dbjz'  # number of employees
DESCRIPTION = 'long_text_mm961fmh'
WEBSITE = 'link_mm943vd3'
LINKEDIN = 'link_mm96cqv8'
COMPANY_EMAIL = 'email_mm968yx7'
COMPANY_PHONE = 'phone_mm96a01r'
CONTACT_PERSON = 'text_mm96433x'
CONTACT_PHONE = 'phone_mm96btp9'
VENDOR_TYPE = 'color_mm95t6mt'
DELIVERY_REGIONS = 'dropdown_mm96c0jr'
CERTIFICATIONS = 'dropdown_mm96f573'
# "Job Functions and Departments" (connect boards): the contact's job title is
# linked to the matching item on that board; the Department mirror then fills itself.
# "Catalogue / Documents" (files column): the vendor's own catalogue, added as a link.
# Never filled with the product page.
CATALOGUE = 'file_mm947aza'
# No catalogue: the AI lists the vendor's products from its website (at most this many) and a
# "Product overview (AI) - <vendor>.csv" file is attached instead.
MAX_OVERVIEW_PRODUCTS = 50
# The AI is asked for at least this many. Fewer: it is asked once more for other products.
# Still fewer (the vendor has no more): the products found are attached - never padded
# with invented ones.
MIN_OVERVIEW_PRODUCTS = 30
JOB_FUNCTIONS = 'board_relation_mm9685qm'
JOB_FUNCTIONS_BOARD = 5108003087

# What a vendor item is still created with when monday rejects a column without
# naming it. Search Source must always be there: with it filled, the "item
# created" automation never treats the new vendor as a request.
CORE_COLUMNS = (SEARCH_SOURCE, PRODUCT_NAME, COUNTRY, LEGAL_NAME, COMPLETE_ADDRESS)

# ---- Search Source labels (exactly as on the board) -----------------------------
AI_BOT = 'AI Bot'
RESEARCH_COMPLETED = 'Research Completed'
MANUAL_RESEARCH = 'Manual research'

# ---- Controlled values ----------------------------------------------------------
VENDOR_TYPES = ('Manufacturer', 'Reseller', 'Distributor')

# Deleiver Regions: regions inside Germany. Only these labels are ever written.
NATIONWIDE = 'Bundesweit'
STATES = (
    'Baden-Württemberg', 'Bayern', 'Berlin', 'Brandenburg', 'Bremen', 'Hamburg', 'Hessen',
    'Mecklenburg-Vorpommern', 'Niedersachsen', 'Nordrhein-Westfalen', 'Rheinland-Pfalz', 'Saarland',
    'Sachsen', 'Sachsen-Anhalt', 'Schleswig-Holstein', 'Thüringen',
)
REGIONS = (NATIONWIDE, *STATES)

# ---- Limits (cost) -------------------------------------------------------------
MAX_CANDIDATES = 10   # step 1 asks for up to this many
VENDORS_WANTED = 3    # created per request: the search goes on until it has 3, within the limits below
FIND_ROUNDS = 2       # step 1 searches per request: a 2nd only when the 1st did not give 3 verified vendors
MAX_CHECKS = 12       # step 2 deep checks per request, over both rounds

# OpenAI calls: 3 retries after the first try, waiting this long before each.
RETRY_DELAYS_SECONDS = (2, 5, 10)

# ---- App settings -------------------------------------------------------------
REQUIRED_SETTINGS = {
    'MONDAY_API_TOKEN': ('MONDAY_API_TOKEN', 'MONDAY_API_KEY'),
    'OPENAI_API_KEY': ('OPENAI_API_KEY',),
}
OPTIONAL_SETTINGS = ('MONDAY_API_VERSION', 'VENDOR_SEARCH_MODEL', 'OPENAI_MODEL', 'OPENAI_TIMEOUT_MS')


def monday_token():
    return setting('MONDAY_API_TOKEN', 'MONDAY_API_KEY')


def monday_api_version():
    return setting('MONDAY_API_VERSION') or '2025-04'


def openai_key():
    return setting('OPENAI_API_KEY')


def model():
    """VENDOR_SEARCH_MODEL if set, else the model Company Enrichment uses."""
    return setting('VENDOR_SEARCH_MODEL', 'OPENAI_MODEL') or 'gpt-4o'


def openai_timeout_seconds():
    try:
        return (float(setting('OPENAI_TIMEOUT_MS')) or 240000) / 1000
    except ValueError:
        return 240.0
