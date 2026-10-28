"""
The connected-board taxonomies behind the `Industry` and `Job Function`
columns.

Both are `board_relation` columns, not text or dropdown: the cell holds a
LINK to an item on a separate taxonomy board, and that link is what the
board's mirrors (Hauptbrachen, Industry Score, Department, Role Score) read
through to reach `Initial Lead Score`. A string cannot be written into one -
the payload is `{"item_ids": [<id>]}` - which is why enrichment left both
blank and the lead score ran on incomplete inputs.

Both lead boards point at the SAME two taxonomy boards, so the cache is
shared across them:

  Industry      -> 5094116229  "Subitems of Sandbox Hauptbranchen & ..."  52 items
  Job Function  -> 5095332326  "Sandbox Abteilung & Funktion"            197 items

Nothing here ever creates a taxonomy item. The names carry the scoring
weights, so an invented one would be a scoring error that looks like data -
the same mistake `create_labels_if_missing` made with the duplicate
"Data authentication required" label. An unmatched value goes to Comments.
"""
import json
import re
import time

from app.core.config import setting
from app.features.company_enrichment.lib.logger import log
from app.features.company_enrichment.services.monday import get_board_items

# The relation columns enrichment fills, by title.
RELATION_TITLES = ['Industry', 'Job Function']


def connected_board_id(column):
    """
    The board a relation column points at.

    `boardIds` is the field to trust: the cold board's Industry column
    (board_relation_mm5b6cag) carries `{"boardIds":[5094116229]}` with no
    `boardId` key at all, so reading `boardId` alone finds nothing on that board
    and only the warm board would ever be filled.
    """
    try:
        settings = json.loads((column or {}).get('settings_str') or '{}')
    except ValueError:
        return ''

    board_ids = settings.get('boardIds')
    first = board_ids[0] if isinstance(board_ids, list) and board_ids else None
    if first is None:
        first = settings.get('boardId')
    return '' if first is None else str(first)


def _normalise(value):
    """
    Folded hard enough to survive how a model retypes German.

    Umlauts are transliterated rather than stripped, so "Geschäftsführung" and
    "geschaeftsfuehrung" land on the same key instead of on "geschftsfhrung" and
    a miss. "&" becomes "und" because the taxonomy is full of "Handel & Vertrieb"
    and a model that types the word out should still match.
    """
    text = (
        str(value).lower()
        .replace('ä', 'ae')
        .replace('ö', 'oe')
        .replace('ü', 'ue')
        .replace('ß', 'ss')
        .replace('&', ' und ')
    )
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def _head(value):
    """The part before the first bracket or semicolon: "Großhandel (Industrie-; ...)" -> "Großhandel"."""
    return re.split(r'[(;,/]', str(value))[0].strip()


def _id_number(entry):
    try:
        return float(entry['id'])
    except (TypeError, ValueError):
        return float('nan')


def match_taxonomy_item(items, wanted):
    """
    Finds the taxonomy item a researched value refers to.

    The model is handed the exact list and asked to echo one name back, so layer
    1 carries almost every case; the rest is the safety net for a model that
    paraphrases or adds its own bracket.

    Ties break to the LOWEST item id - the oldest item wins, the same rule
    find_status_label uses for duplicate labels. This is not cosmetic: "Geschäfts-
    führer" exists twice on the Job Function board with Role Score 13 and 10, so
    an unstable tie-break would make the lead score depend on API row order.

    Returns {id, name, ambiguous} or None.
    """
    value = str(wanted or '').strip()
    if not value or not items:
        return None

    oldest_first = sorted(items, key=_id_number)
    target = _normalise(value)
    target_head = _normalise(_head(value))

    def pick(matches):
        if not matches:
            return None
        first = matches[0]
        ambiguous = [entry['id'] for entry in matches] if len(matches) > 1 else []
        return {'id': first['id'], 'name': first['name'], 'ambiguous': ambiguous}

    # 1. The name exactly as the board spells it.
    exact = [entry for entry in oldest_first if _normalise(entry['name']) == target]
    if exact:
        return pick(exact)

    # 2. Both sides reduced to their leading segment, so "Großhandel" reaches
    #    "Großhandel (Industrie-; Arbeitsschutz-; ...)".
    by_head = [entry for entry in oldest_first if _normalise(_head(entry['name'])) == target_head]
    if by_head:
        return pick(by_head)

    # 3. One is a PREFIX of the other - the model truncated the name, or added to
    #    it. Deliberately not free substring containment: "Handel" appears inside
    #    Großhandel, Einzelhandel and Onlinehandel, and quietly picking one of
    #    those writes a score nobody chose. A wrong link is worse than no link,
    #    because no link is logged and preserved in Comments.
    #
    #    The prefix must end on a WORD boundary, or "Auto" reaches
    #    "Automobilindustrie (inkl. KFZ-Werkstätten; ...)" and four characters
    #    decide an Industry Score. "Großhandel" still reaches "Großhandel
    #    (Industrie-; ...)" because a space follows it.
    #
    #    Shortest name first, so a bare "Handel" prefers the broad category over
    #    an arbitrary specialisation, and every collision is reported as
    #    ambiguous.
    def prefixes(a, b):
        return a == b or a.startswith(f'{b} ')

    by_prefix = sorted(
        (
            entry for entry in oldest_first
            if prefixes(_normalise(entry['name']), target) or prefixes(target, _normalise(entry['name']))
        ),
        key=lambda entry: (len(entry['name']), _id_number(entry)),
    )

    return pick(by_prefix)


# boardId -> items, for the life of the container.
#
# A taxonomy board is a slowly-changing dimension and every run would otherwise
# spend two extra paginated reads on it, against the same complexity budget
# BOARD_ITEM_DELAY_MS exists to protect. A TTL keeps a newly added industry
# from needing a redeploy to become matchable.
_cache = {}


def ttl_ms():
    """TAXONOMY_TTL_MS, read when used so a setting served by monday-code at startup applies."""
    try:
        return float(setting('TAXONOMY_TTL_MS')) or 10 * 60 * 1000
    except ValueError:
        return 10 * 60 * 1000


def _now_ms():
    return time.time() * 1000


def load_taxonomy(board_id):
    key = str(board_id)
    hit = _cache.get(key)
    if hit and _now_ms() - hit['at'] < ttl_ms():
        return hit['items']

    items = get_board_items(key)
    _cache[key] = {'items': items, 'at': _now_ms()}
    return items


def clear_taxonomy_cache():
    _cache.clear()


def load_relation_taxonomies(columns):
    """
    Loads the taxonomy for every relation column enrichment fills.

    A board missing one of the columns, or a column pointing nowhere, simply has
    no entry - the mapper then treats it as "no taxonomy" and skips the column,
    exactly as it does for a column the board does not have.

    Returns {column id: [{id, name}]}.
    """
    by_column_id = {}

    for title in RELATION_TITLES:
        column = next(
            (entry for entry in columns if entry.get('title') == title and entry.get('type') == 'board_relation'),
            None,
        )
        if not column:
            continue

        board_id = connected_board_id(column)
        if not board_id:
            log(f'Column "{title}" ({column["id"]}) has no connected board - skipping')
            continue

        try:
            items = load_taxonomy(board_id)
            if items:
                by_column_id[column['id']] = items
            else:
                log(f'Taxonomy board {board_id} for "{title}" returned no items')
        except Exception as error:
            # A taxonomy that cannot be read costs those two columns, not the run.
            log(f'Could not load taxonomy board {board_id} for "{title}": {error}')

    return by_column_id


def taxonomy_choices(by_column_id, columns, title):
    """The list handed to the model, one name per line."""
    column = next(
        (entry for entry in columns if entry.get('title') == title and entry.get('type') == 'board_relation'),
        None,
    )
    items = by_column_id.get(column['id']) if column else None
    if not items:
        return []

    # De-duplicated: the Job Function board spells "Geschäftsführer" twice and
    # the model does not need to see the collision.
    return list(dict.fromkeys(entry['name'].strip() for entry in items if entry['name'].strip()))
