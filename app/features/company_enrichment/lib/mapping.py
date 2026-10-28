"""
Maps parsed research fields onto board columns.

Columns are resolved by TITLE, not id: the boards this block runs on (see
config/boards.py - the Netgains sandbox boards and the dev sandbox copy)
carry the same titles behind different ids, so a title lookup is what makes
one deployment serve all of them. A column that does not exist on the board
is skipped.
"""
import json
import math
import re

from app.features.company_enrichment.lib.parse import REMOVED_REMARKS
from app.features.company_enrichment.lib.revenue import band_for_figure, format_amount
from app.features.company_enrichment.lib.taxonomy import match_taxonomy_item

# The email now goes to "Company Email", not "Email".
#
# "Email" (lead_email) is the human contact's own address, captured during
# mining; enrichment returns the company's general address, so overwriting
# lead_email destroyed the mined value. NEVER_WRITE keeps that from coming back.
NEVER_WRITE = {'Email'}

# The stage a successfully enriched item lands on.
#
# Enrichment produces the data; a human still has to authenticate it. The stage
# moves in the SAME write as the data, so a lead can never sit fully filled in
# while still reading "Inbound".
#
# This is matched against the labels the column ALREADY has - never written
# verbatim. The first attempt wrote the literal string and monday, with
# `create_labels_if_missing`, happily made a second "Data authentication ..."
# next to the board's own "Data Authentication ...", differing only in one
# capital letter. Matching is case- and punctuation-insensitive and falls back
# to the "data authentication" prefix, so the board owner can rename or
# recapitalise the label without breaking this. If nothing matches, the stage
# is left alone and the run says so - a wrong stage is worse than an old one.
LIFECYCLE_STAGE_TITLE = 'Lifecycle Stage'
LIFECYCLE_STAGE_ENRICHED = 'Data authentication required'

# Enough of the label to recognise it after a rename.
LIFECYCLE_STAGE_PREFIX = 'data authentication'

# The stages enrichment is allowed to move a lead OFF.
#
# The stage write used to be unconditional, and research takes minutes: a lead
# that booked a discovery call while its enrichment was still running got
# dragged back from "Discovery Booked" to "Data Authentication Required" when
# the run finished. Last write wins, and enrichment was always last.
#
# So the stage only moves when the lead is still on a stage that comes BEFORE
# enrichment - an empty stage, "Inbound", or the enrichment stage itself (a
# re-run). Anything the sales flow has advanced to - Discovery Booked, Data
# Complete, Disqualified, Nurture List, Short Route- Discovery - is left exactly
# where it is, and the run log says the stage was held.
#
# An allowlist, not a blocklist of downstream stages: a new downstream label
# added to the board must not silently become overwritable. A board whose leads
# arrive on some other starting stage sets LIFECYCLE_STAGE_SOURCES.
LIFECYCLE_STAGE_SOURCES = ['Inbound', LIFECYCLE_STAGE_ENRICHED]


def _normalise(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value).lower()).strip()


def may_advance_stage(current_label, sources=None):
    """
    Whether enrichment may write the stage, given the stage the item is on NOW.

    Matched the same way as the labels themselves - case- and
    punctuation-insensitive, with the "data authentication" prefix as the
    fallback - so a renamed or recapitalised label does not turn the guard off.
    """
    if sources is None:
        sources = LIFECYCLE_STAGE_SOURCES
    current = _normalise(current_label)

    # Nothing to protect: the lead has no stage at all.
    if not current:
        return True

    # Any "Data Authentication ..." variant, including the casing duplicate an
    # earlier build invented, is still a pre-enrichment stage.
    if current.startswith(_normalise(LIFECYCLE_STAGE_PREFIX)):
        return True

    return any(_normalise(source) == current for source in sources)


# title on the board <- field from the research output.
#
# `constant` writes a fixed value instead of a researched one.
COLUMN_PLAN = [
    {'title': LIFECYCLE_STAGE_TITLE, 'constant': LIFECYCLE_STAGE_ENRICHED, 'match_prefix': LIFECYCLE_STAGE_PREFIX},
    {'title': 'Company / Customer Name', 'field': 'CORRECT_NAME'},
    {'title': 'Full Address', 'field': 'CORRECT_ADDRESS'},
    {'title': 'Address Line 1', 'field': 'ADDRESS_LINE_1'},
    {'title': 'Address Line 2', 'field': 'ADDRESS_LINE_2'},
    {'title': 'Address Line 3', 'field': 'ADDRESS_LINE_3'},
    {'title': 'Postal Code', 'field': 'POSTAL_CODE'},
    {'title': 'City', 'field': 'CITY'},
    {'title': 'State', 'field': 'STATE'},
    {'title': 'District', 'field': 'DISTRICT'},
    {'title': 'Country', 'field': 'COUNTRY'},
    # dialling_code is defined further down.
    {'title': 'Country Code', 'field': 'COUNTRY_CODE', 'derive': lambda fields, column: dialling_code(fields, column)},
    {'title': 'Registration Number', 'field': 'REGISTRATION_NUMBER'},
    {'title': 'D&B Number', 'field': 'D_AND_B_NUMBER'},
    {'title': 'Website', 'field': 'HOMEPAGE'},
    {'title': 'LinkedIn Profile', 'field': 'LINKEDIN_PROFILE'},
    {'title': 'Contact Name', 'field': 'CONTACT_NAME'},
    {'title': 'Company Email', 'field': 'COMPANY_EMAIL'},
    {'title': 'Main Phone', 'field': 'MAIN_PHONE'},
    {'title': 'Mobile Number', 'field': 'MOBILE_NUMBER'},
    {'title': 'Fax', 'field': 'FAX'},
    {'title': 'Phone Type', 'field': 'PHONE_TYPE'},
    {'title': 'Company Size', 'field': 'COMPANY_SIZE'},
    # `figure_field` is the raw revenue the research found ("EUR 30,000,000"). It
    # is placed into the column's bands by arithmetic (lib/revenue.py), converted
    # into the bands' currency first; the band the model picked is only used when
    # there is no figure or it cannot be placed.
    {'title': 'Estimated Annual Revenue', 'field': 'ESTIMATED_ANNUAL_REVENUE', 'figure_field': 'ANNUAL_REVENUE_FIGURE'},
    {'title': 'Company Structure', 'field': 'COMPANY_STRUCTURE'},
    {'title': 'Ownership Type', 'field': 'OWNERSHIP_TYPE', 'fallback_field': 'CLASSIFICATION'},
    # Both are board_relation columns: the value written is a link to an item on
    # a taxonomy board, and the board's mirrors read the score through that link.
    # Left out of the plan entirely until now, which is why Industry Score, Role
    # Score, Hauptbrachen and Department were all empty and Initial Lead Score
    # scored every enriched lead on incomplete inputs.
    {'title': 'Industry', 'field': 'INDUSTRY'},
    {'title': 'Job Function', 'field': 'JOB_FUNCTION'},
    {'title': 'Comments', 'field': '__NOTES__'},
]

# Empty values are filled with "N/A".
#
# A link, email or phone column carries its own display label, so "N/A" can be
# written into it and the cell reads N/A instead of sitting blank - that is
# what puts N/A in LinkedIn Profile, Website and Mobile Number.
#
# A dropdown only gets N/A when "N/A" is already one of its options. Writing
# `{labels: ["N/A"]}` used to create that option on any dropdown that lacked
# it, which is exactly the kind of invented option this app must not make.
#
# Number, date and country columns are the exception: monday parses those into
# a numeric or ISO value and has nowhere to keep the string "N/A". They stay
# empty. Nothing here can break a write - change_multiple_column_values is
# all-or-nothing, but write_columns drops whatever monday rejects, names it in
# the log, and retries the rest.
NA_TEXT = 'N/A'

NA_BY_TYPE = {
    'text': lambda: NA_TEXT,
    'long_text': lambda: {'text': NA_TEXT},
    'link': lambda: {'url': NA_TEXT, 'text': NA_TEXT},
    'email': lambda: {'email': NA_TEXT, 'text': NA_TEXT},
    'phone': lambda: {'phone': NA_TEXT, 'countryShortName': ''},
}


def _na_value_for(column):
    if column.get('type') == 'dropdown':
        option = find_status_label(column, NA_TEXT)
        return {'ids': [option['index']]} if option else None
    make = NA_BY_TYPE.get(column.get('type'))
    return make() if make else None


def option_choices(columns):
    """
    The options the model is shown for each controlled column, keyed by the
    research field that feeds it.

    Without the list the model answered from its own vocabulary ("€25M",
    "Privately held") and almost nothing matched the board's options, so the
    column fell back to N/A. Handing it the board's exact labels is the same fix
    the Industry / Job Function taxonomies got. Columns with a fixed or derived
    value (Lifecycle Stage, Country Code) are not asked for, and "N/A" itself is
    left out - "Not found" already produces it.

    Returns {field: [label, ...]}.
    """
    choices = {}

    for entry in COLUMN_PLAN:
        if not entry.get('field') or 'constant' in entry or entry.get('derive'):
            continue

        column = next((candidate for candidate in columns if candidate.get('title') == entry['title']), None)
        if not column or column.get('type') not in ('dropdown', 'status'):
            continue

        labels = [
            option['label'].strip()
            for option in status_labels(column)
            if _normalise(option['label'].strip()) != _normalise(NA_TEXT)
        ]

        if labels:
            choices[entry['field']] = list(dict.fromkeys(labels))

    return choices


EMAIL_RE = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]{2,}')


def build_column_values(columns, fields, relations=None, fx=None):
    """
    Builds the `column_values` payload.

    Comments is composed last, whatever its position in the plan, so it can carry
    the values no controlled column would accept.

    `relations` carries the taxonomy items for the board_relation columns, keyed
    by column id - fetched before the write because a relation cannot be resolved
    from the researched string alone. Absent, those columns are skipped, so this
    stays a pure function and the mapper remains testable without a network.

    `fx` is `{rates, date}` from services/fx.py, for converting a revenue figure
    into the currency of the board's bands. Absent, a figure in another currency
    cannot be placed and the band the model chose is used instead.

    Returns a dict with: values, filled, skipped, unmatched [{title, value}],
    linked [{title, name, id}], ambiguous [{title, name, ids}], cleaned [title],
    banded [{title, figure, label?, reason?, ...}].
    """
    relations = relations or {}
    rates = fx.get('rates') if fx else None

    by_title = {}
    for column in columns:
        by_title.setdefault(column.get('title'), column)

    values = {}
    filled = []
    skipped = []
    unmatched = []
    linked = []
    ambiguous = []
    banded = []

    notes_entry = next((entry for entry in COLUMN_PLAN if entry.get('field') == '__NOTES__'), None)

    for entry in COLUMN_PLAN:
        if entry['title'] in NEVER_WRITE or entry is notes_entry:
            continue

        column = by_title.get(entry['title'])
        if not column:
            continue

        if 'constant' in entry:
            raw = entry['constant']
        elif entry.get('derive'):
            raw = entry['derive'](fields, column)
        else:
            raw = (
                fields.get(entry['field'])
                or (fields.get(entry['fallback_field']) if entry.get('fallback_field') else '')
                or ''
            )

        # A relation resolves against the taxonomy board's items rather than the
        # column's own settings, so it is handled here where `relations` is in
        # scope. Anything it links is reported so the run log can name it.
        if column.get('type') == 'board_relation':
            match = match_taxonomy_item(relations.get(column['id']), raw)

            if match:
                values[column['id']] = {'item_ids': [match['id']]}
                linked.append({'title': entry['title'], 'name': match['name'], 'id': match['id']})
                if match['ambiguous']:
                    ambiguous.append({'title': entry['title'], 'name': match['name'], 'ids': match['ambiguous']})
                continue

            # No item to point at. A relation has no "N/A" to fall back on, so the
            # researched value is preserved in Comments and the cell stays empty.
            researched_relation = str(raw or '').strip()
            if researched_relation:
                unmatched.append({'title': entry['title'], 'value': researched_relation})
            skipped.append(entry['title'])
            continue

        # A researched figure is placed into the band that contains it, which text
        # matching cannot do - "€30 million" spells no band. When it cannot be
        # placed (no figure, no rate, no band covers it) the model's own band
        # choice below still gets its chance.
        figure = str(fields.get(entry['figure_field']) or '').strip() if entry.get('figure_field') else ''
        if figure and column.get('type') == 'dropdown':
            placed = band_for_figure(status_labels(column), figure, rates) or {
                'reason': 'no amount could be read from it',
            }
            banded.append({'title': entry['title'], 'figure': figure, **placed})
            if placed.get('label'):
                values[column['id']] = {'ids': [placed['index']]}
                continue

        formatted = _format_value(column, raw, fields, entry)

        if formatted is not None:
            values[column['id']] = formatted
            continue

        # The model answered the band with one that is not an option - "$10M-$50M"
        # on a board of EUR bands. Read it as a figure (a range by its midpoint),
        # convert it, and take the band that contains it or the nearest one, so the
        # cell still gets one of the column's own options.
        answer = str(raw or '').strip()
        if entry.get('figure_field') and answer and column.get('type') == 'dropdown':
            placed = band_for_figure(status_labels(column), answer, rates)
            if placed and placed.get('label'):
                values[column['id']] = {'ids': [placed['index']]}
                banded.append({'title': entry['title'], 'figure': answer, **placed})
                continue

        # A real value the column's own vocabulary has no room for - keep it in the
        # notes rather than dropping it or inventing an option for it.
        researched = str(raw or '').strip()
        if researched and column.get('type') in ('dropdown', 'status'):
            unmatched.append({'title': entry['title'], 'value': researched})

        # Nothing usable for this column - say so in the cell where monday can hold it.
        na_value = _na_value_for(column)
        if na_value is not None:
            values[column['id']] = na_value
            filled.append(entry['title'])
        else:
            skipped.append(entry['title'])

    notes_column = by_title.get(notes_entry['title']) if notes_entry else None
    if notes_column:
        notes = _format_value(
            notes_column,
            _compose_notes(fields, unmatched, banded, fx.get('date') if fx else ''),
            fields,
            notes_entry,
        )
        if notes is not None:
            values[notes_column['id']] = notes

    # The name and address columns a remark was cut out of, for the run log.
    cleaned = list(dict.fromkeys(_title_of_field(entry['key']) for entry in fields.get(REMOVED_REMARKS) or []))

    return {
        'values': values,
        'filled': filled,
        'skipped': skipped,
        'unmatched': unmatched,
        'linked': linked,
        'ambiguous': ambiguous,
        'cleaned': cleaned,
        'banded': banded,
    }


def _describe_banding(entry, fx_date):
    """"32.4M USD at exchange rate of 2026-10-15 -> 30M-50M USD", or why it was not placed."""
    if not entry.get('label'):
        return f"not placed ({entry.get('reason')})"

    if entry.get('from') and entry['from'] != entry['currency']:
        converted = (
            f"{format_amount(entry['original'], entry['from'])} = {format_amount(entry['amount'], entry['currency'])}"
            f" at exchange rate{f' of {fx_date}' if fx_date else ''}"
        )
    else:
        converted = format_amount(entry['amount'], entry['currency'])
    return f"{converted} -> {'nearest option ' if entry['nearest'] else ''}{entry['label']}"


def _title_of_field(key):
    return next((entry['title'] for entry in COLUMN_PLAN if entry.get('field') == key), key)


def _format_value(column, raw, fields, entry=None):
    """Returns the monday-shaped value, or None when there is nothing to write."""
    entry = entry or {}
    value = str(raw or '').strip()
    if not value:
        return None

    column_type = column.get('type')

    if column_type == 'text':
        return value

    if column_type == 'long_text':
        return {'text': value[:2000]}

    # A dropdown is a controlled vocabulary - "Country Code" holds dialling
    # codes, and writing "DE" into it created a "DE" option next to +49. Only
    # an option the column already has is ever written, and by id, so no
    # string can create one. An unmatched value is reported in Comments, and a
    # dropdown whose options could not be read gets nothing at all.
    if column_type == 'dropdown':
        match = (
            find_status_label(column, value, entry.get('match_prefix'))
            or find_status_label(column, re.split(r'[;,]', value)[0].strip(), entry.get('match_prefix'))
        )
        return {'ids': [match['index']]} if match else None

    if column_type == 'email':
        match = EMAIL_RE.search(value)
        return {'email': match.group(0), 'text': match.group(0)} if match else None

    if column_type == 'phone':
        digits = re.sub(r'[^\d+]', '', value)
        if len(re.sub(r'\D', '', digits)) < 6:
            return None
        return {'phone': digits, 'countryShortName': _country_code_of(fields)}

    if column_type == 'link':
        url = value if value.startswith('http') else f"https://{re.sub(r'^/+', '', value)}"
        if not re.match(r'^https?://[^\s.]+\.[^\s]{2,}$', url, re.IGNORECASE):
            return None
        return {'url': url, 'text': re.sub(r'/$', '', re.sub(r'^https?://', '', url))}

    if column_type == 'country':
        code = _country_code_of(fields)
        return {'countryCode': code, 'countryName': fields.get('COUNTRY') or value} if code else None

    if column_type == 'numbers':
        digits = re.sub(r'[^\d]', '', value)
        return str(int(digits)) if digits else None

    if column_type == 'date':
        return {'date': value} if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else None

    # By index, against a label the column already has. Writing `{label: ...}`
    # with `create_labels_if_missing` invents a near-duplicate on any casing
    # difference, which is exactly the bug this replaced.
    if column_type == 'status':
        match = find_status_label(column, value, entry.get('match_prefix'))
        return {'index': match['index']} if match else None

    return None


def _to_index(value):
    """An option id as monday sends it ("3", 3, 3.0) -> 3, or None when it is not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip() or 0)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def status_labels(column):
    """
    The labels a status or dropdown column already carries.

    `settings_str` is JSON-in-a-string and the two column types disagree on its
    shape - status is `{"labels":{"0":"Inbound"}}`, dropdown is
    `{"labels":[{"id":1,"name":"+49"}]}`. Both normalise to {index, label}.

    A dropdown option deactivated in monday stays in `labels` and is listed by id
    under `deactivated_labels`; it is no longer offered on the board, so it is not
    offered here either.
    """
    try:
        settings = json.loads(column.get('settings_str') or '{}')
    except ValueError:
        return []
    if not isinstance(settings, dict):
        return []

    deactivated_labels = settings.get('deactivated_labels')
    deactivated = {
        _to_index(entry.get('id') if isinstance(entry, dict) and entry.get('id') is not None else entry)
        for entry in (deactivated_labels if isinstance(deactivated_labels, list) else [])
    }

    labels = settings.get('labels')
    if isinstance(labels, list):
        entries = [
            {
                'index': _to_index(entry.get('id')) if isinstance(entry, dict) else None,
                'label': _label_text(entry.get('name') if isinstance(entry, dict) else None),
            }
            for entry in labels
        ]
    elif isinstance(labels, dict):
        entries = [{'index': _to_index(index), 'label': _label_text(label)} for index, label in labels.items()]
    else:
        entries = []

    usable = [
        entry for entry in entries
        if entry['label'].strip() and entry['index'] is not None and entry['index'] not in deactivated
    ]
    return sorted(usable, key=lambda entry: entry['index'])


def _label_text(label):
    return '' if label is None else str(label)


def find_status_label(column, wanted, prefix=None):
    """
    Finds an existing label on a status column.

    Ties break to the LOWEST index: the board's own label was created before any
    duplicate this app may have added, so the older one wins.

    Returns {index, label} or None.
    """
    labels = status_labels(column)
    target = _normalise(wanted)

    exact = next((entry for entry in labels if _normalise(entry['label']) == target), None)
    if exact:
        return exact

    if not prefix:
        return None
    normalised_prefix = _normalise(prefix)
    return next((entry for entry in labels if _normalise(entry['label']).startswith(normalised_prefix)), None)


# "Country Code" is a dropdown of dialling codes (+49, +1, +212 ...), not the
# ISO code. The ISO code still goes to the `country` column, which wants it.
#
# The researched phone numbers are the better source - they carry the dialling
# code directly - so they are tried first and the ISO map is the fallback for a
# lead with no phone at all. Longest match wins, or +1 would swallow +212.
ISO_TO_DIALLING = {
    'AT': '+43', 'BE': '+32', 'CH': '+41', 'CZ': '+420', 'DE': '+49', 'DK': '+45', 'ES': '+34',
    'FR': '+33', 'GB': '+44', 'IE': '+353', 'IT': '+39', 'LU': '+352', 'NL': '+31', 'PL': '+48',
    'PT': '+351', 'SE': '+46', 'US': '+1',
}


def dialling_code(fields, column):
    available = sorted(
        (label for label in (entry['label'].strip() for entry in status_labels(column)) if re.fullmatch(r'\+\d+', label)),
        key=len,
        reverse=True,
    )

    for phone in [fields.get('MAIN_PHONE'), fields.get('MOBILE_NUMBER'), fields.get('FAX')]:
        digits = re.sub(r'[^\d+]', '', str(phone or ''))
        if not digits.startswith('+'):
            continue

        match = next((label for label in available if digits.startswith(label)), None)
        if match:
            return match

    return ISO_TO_DIALLING.get(_country_code_of(fields), '')


def _country_code_of(fields):
    code = str(fields.get('COUNTRY_CODE') or '').strip().upper()
    if re.fullmatch(r'[A-Z]{2}', code):
        return code
    return 'DE' if re.search(r'deutschland|germany', str(fields.get('COUNTRY') or ''), re.IGNORECASE) else ''


def _compose_notes(fields, unmatched, banded, fx_date=''):
    """
    Everything the research produced that has no column of its own - VAT number,
    registry court, confidences, sources, company status - collected into the
    Comments column so the verification trail is not lost.
    """
    lines = []

    def add(label, key):
        value = fields.get(key)
        lines.append(f'{label}: {value}' if value else f'{label}: {NA_TEXT}')

    add('VAT (USt-IdNr)', 'UID_NUMBER')
    add('VAT confidence', 'VAT_CONFIDENCE')
    add('HRB confidence', 'HRB_CONFIDENCE')
    add('Registry court', 'REGISTRY_COURT')
    add('Handelsregister verified', 'HANDELSREGISTER_VERIFIED')
    add('Company status', 'COMPANY_STATUS')
    add('Classification', 'CLASSIFICATION')
    add('Overall confidence', 'CONFIDENCE')
    add('Verification source', 'VERIFICATION_SOURCE')
    add('Registry source', 'REGISTRY_SOURCE')

    # How a revenue figure reached its band, or why it did not.
    for entry in banded:
        lines.append(f"{entry['title']} figure: {entry['figure']} - {_describe_banding(entry, fx_date)}")

    # Researched, but the column's options had no home for it.
    for entry in unmatched:
        lines.append(f"{entry['title']} (no matching option): {entry['value']}")

    # Remarks the model attached to the name or address - kept out of those
    # cells, but not thrown away.
    for entry in fields.get(REMOVED_REMARKS) or []:
        lines.append(f"{_title_of_field(entry['key'])} (note removed): {entry['text']}")

    if fields.get('NOTES'):
        lines.extend(['', fields['NOTES']])

    return '\n'.join(lines)
