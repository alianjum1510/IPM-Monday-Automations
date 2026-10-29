import re
import time

from app.features.company_enrichment.config.boards import restrict_to_allowed_options
from app.features.company_enrichment.config.env import env
from app.features.company_enrichment.lib.country import country_code, country_from_input, country_name
from app.features.company_enrichment.lib.logger import log
from app.features.company_enrichment.lib.mapping import (
    LIFECYCLE_STAGE_ENRICHED,
    LIFECYCLE_STAGE_SOURCES,
    LIFECYCLE_STAGE_TITLE,
    NAME_OVERFLOW_TITLE,
    NAME_TITLE,
    build_column_values,
    may_advance_stage,
    option_choices,
    status_labels,
)
from app.features.company_enrichment.lib.parse import parse_enrichment
from app.features.company_enrichment.lib.prompt import build_prompt
from app.features.company_enrichment.lib.taxonomy import load_relation_taxonomies, taxonomy_choices
from app.features.company_enrichment.services.fx import get_rates
from app.features.company_enrichment.services.monday import get_board, get_item, write_columns
from app.features.company_enrichment.services.openai import classify_country, research

# Address parts, in the order they read on the board.
ADDRESS_PARTS = [
    'Address Line 1',
    'Address Line 2',
    'Address Line 3',
    'Postal Code',
    'City',
    'District',
    'State',
    'Country',
]


def enrich_item(requested_board_id, item_id):
    """
    The whole job for one item: read it, research it, write the columns back.
    Runs detached from the HTTP response - monday only waits for the ack.
    """
    item = get_item(item_id)

    if not item:
        raise Exception(f'item {item_id} not found')

    # The board is the one the ITEM lives on, not the id the request carried.
    # The dev sandbox copy and the original board share column ids but not their
    # dropdown options, so reading the options off the wrong board - a request
    # with no board id falling back to DEFAULT_BOARD_ID, or a recipe pointing at
    # the other board - wrote the original board's option ids into a dev item.
    # The item's own board makes the dev board use dev options, always.
    item_board = item.get('board') or {}
    board_id = str(item_board['id']) if item_board.get('id') else str(requested_board_id)
    if str(requested_board_id) != board_id:
        log(
            f'Item {item_id}: request named board {requested_board_id} but the item is on board {board_id} '
            f'- using {board_id}'
        )

    if item.get('state') and item['state'] != 'active':
        log(f"Item {item_id}: {item['state']} — skipping", item_id=str(item_id), board_id=board_id, skipped=item['state'])
        return {'success': True, 'boardId': board_id, 'itemId': str(item_id), 'skipped': item['state']}

    full_board = get_board(board_id)
    # Only the values allowed for THIS board (config/boards.py) are ever
    # offered to the AI or written - the dev sandbox uses its own list.
    board = {**full_board, 'columns': restrict_to_allowed_options(board_id, full_board['columns'])}
    by_id = {column['id']: column for column in board['columns']}
    text = {}
    for value in item.get('column_values') or []:
        column = by_id.get(value['id'])
        if column:
            text[column['title']] = (value.get('text') or '').strip()

    # A name over MAX_NAME_LENGTH was split by customer_name_split; the research
    # needs it whole, overflow included.
    company_name = (
        ' '.join(part for part in (text.get(NAME_TITLE), text.get(NAME_OVERFLOW_TITLE)) if part)
        or item.get('name')
        or ''
    )
    address = _compose_address(text)

    if not company_name and not address:
        log(
            f'Item {item_id}: no company name or address — skipping',
            item_id=str(item_id), board_id=board_id, skipped='no company name or address',
        )
        return {'success': True, 'boardId': board_id, 'itemId': str(item_id), 'enriched': False}

    country = _classify_lead_country(text.get('Country'), address)

    classified = f"{country['name']} from {country['source']}" if country else 'unclassified'
    log(
        f'Item {item_id}: enriching "{company_name}" / "{address}" (country: {classified})',
        item_id=str(item_id), board_id=board_id, company=company_name, address=address,
        country=country['code'] if country else None,
    )

    # Industry and Job Function are board_relation columns, so their vocabulary
    # lives on other boards and has to be read BEFORE the research: the model is
    # given the exact list and asked to echo one entry back, because the taxonomy
    # is German and a free-text guess would never match. Cached per container, so
    # this is normally free.
    relations = load_relation_taxonomies(board['columns'])
    choices = {
        'industries': taxonomy_choices(relations, board['columns'], 'Industry'),
        'job_functions': taxonomy_choices(relations, board['columns'], 'Job Function'),
        # The dropdowns' own options, already on the board read above - the model
        # picks from these, and nothing outside them is ever written.
        'options': option_choices(board['columns']),
    }

    answer = research(build_prompt(company_name, address, choices, country['name'] if country else ''))
    fields = parse_enrichment(answer['text'])

    if not fields:
        raise Exception(f'no parsable fields in the model output for item {item_id}')

    # Any revenue the research returns - the figure or the band it picked - may be
    # in USD, PKR or another currency and is converted into the board's EUR bands.
    # Cached for hours, so this is normally free.
    fx = get_rates() if fields.get('ANNUAL_REVENUE_FIGURE') or fields.get('ESTIMATED_ANNUAL_REVENUE') else None

    result = build_column_values(board['columns'], fields, relations, fx, max_name_length=env.max_name_length)
    values = result['values']

    if env.board_item_delay_ms:
        time.sleep(env.board_item_delay_ms / 1000)

    # The stage read at the top of this run is minutes stale by the time the
    # research comes back, and the lead may have moved on in the meantime - that
    # is how a booked discovery call ended up back on "Data Authentication
    # Required". Re-read it as late as possible and drop the stage from the write
    # unless the lead is still on a pre-enrichment stage. The data still lands.
    stage_column = next((entry for entry in board['columns'] if entry['title'] == LIFECYCLE_STAGE_TITLE), None)
    held = _hold_stage_if_advanced(stage_column, item_id, values)

    write = write_columns(board_id, item_id, values)

    # The stage column travels with the data; if it was held, monday rejected it,
    # or the column has no label to match, the item is still on its old stage and
    # that has to be visible in the log.
    stage = _describe_stage_write(board['columns'], values, write['dropped'], held)

    verified = 'yes' if re.fullmatch(r'yes', fields.get('HANDELSREGISTER_VERIFIED') or '', re.IGNORECASE) else 'no'
    registration = fields.get('REGISTRATION_NUMBER') or 'none'
    confidence = fields.get('CONFIDENCE') or 'unknown'
    searches = answer['search_count'] if answer['searched'] else 'disabled'

    message = (
        f"Item {item_id}: updated {write['written']} columns "
        f"(verified={verified}, reg={registration}, hr={fields.get('HANDELSREGISTER_VERIFIED') or 'No'}, "
        f'confidence={confidence}, lifecycle stage={stage}) '
        f"[N/A filled: {len(result['filled'])}, left empty: {len(result['skipped'])}, "
        f'web searches: {searches}]'
    )
    # Names the option a board owner may want to add to a dropdown.
    if result['unmatched']:
        message += ' no matching option: ' + ', '.join(
            f"{entry['title']}=\"{entry['value']}\"" for entry in result['unmatched']
        )
    # Where the researched name went - or that the lead's own name was kept.
    if result['name_split']:
        overflow = result['name_split']['overflow']
        message += (
            f" name: {result['name_split']['name_chars']} chars, rest to {NAME_OVERFLOW_TITLE} \"{overflow}\""
            if overflow else f' name: fits, {NAME_OVERFLOW_TITLE} cleared'
        )
    elif NAME_TITLE in result['skipped']:
        message += ' name: none researched, kept as it was'
    # The model annotated the name or address; the note went to Comments.
    if result['cleaned']:
        message += f" notes removed from: {', '.join(result['cleaned'])}"
    # Where the revenue figure landed, or why it fell back to the model's band.
    if result['banded']:
        message += ' banded: ' + ', '.join(
            f"{entry['title']}=\"{entry['figure']}\" -> "
            + (f"\"{entry['label']}\"" if entry.get('label') else f"not placed ({entry.get('reason')})")
            for entry in result['banded']
        )
    # The relations feed Initial Lead Score, so the run says what they landed on.
    if result['linked']:
        message += ' linked: ' + ', '.join(f"{entry['title']}=\"{entry['name']}\"" for entry in result['linked'])
    # Two taxonomy items share a name and they may carry different scores.
    if result['ambiguous']:
        message += ' ambiguous taxonomy: ' + ', '.join(
            f"{entry['title']}=\"{entry['name']}\" ({'/'.join(entry['ids'])}, took {entry['ids'][0]})"
            for entry in result['ambiguous']
        )
    log(
        message,
        item_id=str(item_id),
        board_id=board_id,
        columns_written=write['written'],
        columns_rejected=write['dropped'],
        verified=verified == 'yes',
        registration_number=fields.get('REGISTRATION_NUMBER') or None,
        confidence=fields.get('CONFIDENCE') or None,
        lifecycle_stage=stage,
        na_filled=len(result['filled']),
        left_empty=len(result['skipped']),
        web_searches=searches,
        no_matching_option={entry['title']: entry['value'] for entry in result['unmatched']},
        linked={entry['title']: entry['name'] for entry in result['linked']},
    )

    return {
        'success': True,
        'boardId': board_id,
        'itemId': str(item_id),
        'enriched': True,
        'verified': verified == 'yes',
        'columnsWritten': write['written'],
        'naFilled': len(result['filled']),
        'linked': [entry['title'] for entry in result['linked']],
    }


def _hold_stage_if_advanced(column, item_id, values):
    """
    Removes the stage from the write when the lead has moved on since the run
    started, and reports the stage it was left on.

    The extra read costs one query per run - cheap next to minutes of research,
    and it is the only thing standing between a mid-run booking and a stage that
    silently walks backwards. monday has no compare-and-swap, so the gap between
    this read and the write cannot be closed entirely; it goes from minutes to
    milliseconds.

    Returns the stage the write was held at, or '' if it may proceed.
    """
    if not column or column['id'] not in values:
        return ''

    fresh = get_item(item_id)
    current = next((entry for entry in (fresh or {}).get('column_values') or [] if entry['id'] == column['id']), None)
    label = ((current or {}).get('text') or '').strip()

    sources = env.lifecycle_stage_sources or LIFECYCLE_STAGE_SOURCES
    if may_advance_stage(label, sources):
        return ''

    del values[column['id']]
    return label


def _describe_stage_write(columns, values, dropped, held=''):
    """
    What actually happened to the Lifecycle Stage column, for the run log.

    Two of these need a human. "held" means the lead advanced while the research
    ran, so the data landed on a lead that is already further down the funnel.
    "no matching label" means the column carries nothing recognisable as the
    post-enrichment stage, so the lead keeps whatever stage it had.
    """
    column = next((entry for entry in columns if entry['title'] == LIFECYCLE_STAGE_TITLE), None)
    if not column:
        return 'no such column on this board'

    if held:
        return f'held at "{held}" - the lead advanced while the research ran'

    value = values.get(column['id'])
    if not value:
        available = ' | '.join(entry['label'] for entry in status_labels(column))
        return f'no matching label for "{LIFECYCLE_STAGE_ENRICHED}" (column has: {available or "none"})'

    if column['id'] in dropped:
        return 'REJECTED by monday - stage unchanged'

    written = next((entry for entry in status_labels(column) if entry['index'] == value.get('index')), None)
    return f'"{written["label"] if written else value.get("index")}"'


def _classify_lead_country(country_column, address):
    """
    The country the research is scoped to, settled BEFORE the research runs.

    What the user entered decides it when it can - the Country column, a country
    name or a postal prefix in the address. Only an address that names no country
    goes to the model, which places it by its city, postal code and region.

    Returns {code, name, source} or None.
    """
    from_input = country_from_input(country_column, address)
    if from_input or not address:
        return from_input

    code = country_code(classify_country(address))
    return {'code': code, 'name': country_name(code), 'source': 'address (city / postal code)'} if code else None


def _compose_address(text):
    """
    Prefers the structured parts, because "Address" alone is often just a street.
    Falls back to whatever single address column the board has.
    """
    parts = [text[title] for title in ADDRESS_PARTS if text.get(title)]
    if parts:
        return ', '.join(parts)
    return text.get('Full Address') or text.get('Address') or ''
