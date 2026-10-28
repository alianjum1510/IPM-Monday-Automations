"""
The boards this block runs on, by board id.

Every board is enriched the same way: columns are resolved by TITLE and each
dropdown's options are read from the board the item lives on, so the
original and the dev copy each use their own options.

`allowed` narrows that further: per column title, the ONLY values the AI may
be offered and that may be written. Options the board has but the list does
not name (old English duplicates such as "Landline") are invisible to the run.
A column with no list keeps all of its board options. A value on the list
that the board does not have is ignored and logged - nothing is ever created.
"""
import json

from src.lib.logger import log

BOARDS = {
    '5100825258': {'environment': 'Netgains sandbox', 'name': 'Warm Lead Mining Board'},
    '5106281544': {
        'environment': 'Dev sandbox',
        'name': 'Warm Lead Mining Board (Copy)',
        # The dev sandbox dropdowns as they stand (screenshots and API, 2026-10-26).
        # The English entries marked below are duplicates an older build created;
        # delete a line here and the AI can no longer pick that value on dev.
        'allowed': {
            'Estimated Annual Revenue': [
                '< 1M EUR', '1M-10M EUR', '10M-50M EUR', '50M-100M EUR', '100M-500M EUR', '500M+ EUR', 'N/A',
            ],
            'Company Structure': [
                'Einzelgesellschaft', 'Holdinggesellschaft', 'Muttergesellschaft', 'Tochtergesellschaft',
                'Zweigniederlassung', 'Joint Venture', 'Partnergesellschaft', 'GmbH & Co. KG', 'N/A',
            ],
            'Ownership Type': [
                'Privatunternehmen', 'Öffentliche Institution', 'Gemeinnützige Organisation', 'Genossenschaft', 'N/A',
                'Private',  # English duplicate
                'Municipality',  # English duplicate
            ],
            'Phone Type': [
                'Festnetznummer', 'Mobilnummer', 'Andere', 'N/A',
                'Landline',  # English duplicate
                'Mobile',  # English duplicate
                'VoIP',  # English
            ],
        },
    },
    '5100463291': {'environment': 'Netgains sandbox', 'name': 'Lead Mining Board'},
}


def describe_board(board_id):
    """"Dev sandbox - Warm Lead Mining Board (Copy)", for the run log."""
    board = BOARDS.get(str(board_id))
    if board:
        return f"{board['environment']} - {board['name']}"
    return f'board {board_id} is not in src/config/boards.py - enriching it by column titles anyway'


def _same(a, b):
    return str(a).strip().lower() == str(b).strip().lower()


def restrict_to_allowed_options(board_id, columns):
    """
    The board's columns with every listed dropdown cut down to its `allowed`
    values. Everything downstream - the options in the prompt, the matching, the
    N/A fill, the revenue bands - reads the options from these columns, so a
    value missing from the list can be neither offered nor written.
    """
    allowed = BOARDS.get(str(board_id), {}).get('allowed') or {}
    restricted = []

    for column in columns:
        allowed_values = allowed.get(column.get('title'))
        if not allowed_values or column.get('type') not in ('dropdown', 'status'):
            restricted.append(column)
            continue

        try:
            settings = json.loads(column.get('settings_str') or '{}')
        except ValueError:
            restricted.append(column)
            continue

        def is_allowed(name):
            return any(_same(value, name) for value in allowed_values)

        raw_labels = settings.get('labels') or {}
        if isinstance(raw_labels, list):
            labels = [entry for entry in raw_labels if is_allowed((entry or {}).get('name'))]
            present = [entry.get('name') for entry in labels]
        else:
            labels = {index: name for index, name in raw_labels.items() if is_allowed(name)}
            present = list(labels.values())

        missing = [value for value in allowed_values if not any(_same(name, value) for name in present)]
        if missing:
            listed = ', '.join(f'"{value}"' for value in missing)
            log(f'Board {board_id}: "{column["title"]}" has no option {listed} - not offered')

        restricted.append({**column, 'settings_str': json.dumps({**settings, 'labels': labels})})

    return restricted
