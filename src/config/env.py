"""
Environment for the monday-code deployment.

These keys already exist on app 11727119 (`mapps code:env -i 11727119 -m
list-keys`) - env vars live on the app, not the version, so a redeployed
version inherits them.
"""
import os


def _number(name, default):
    """`Number(process.env.X) || default`: unset, unparsable or 0 means the default."""
    try:
        return float(os.environ.get(name, '')) or default
    except ValueError:
        return default


class _Monday:
    api_token = os.environ.get('MONDAY_API_TOKEN') or os.environ.get('MONDAY_API_KEY') or ''
    api_url = 'https://api.monday.com/v2'
    api_version = os.environ.get('MONDAY_API_VERSION') or '2024-10'


class _OpenAI:
    api_key = os.environ.get('OPENAI_API_KEY') or ''
    model = os.environ.get('OPENAI_MODEL') or 'gpt-4o'
    # Optional cheaper model for the one-word country classification; defaults to `model`.
    country_model = os.environ.get('OPENAI_COUNTRY_MODEL') or ''
    timeout_ms = _number('OPENAI_TIMEOUT_MS', 240000)


class _Fx:
    """ECB exchange rates for placing a revenue figure into the board's bands."""

    url = os.environ.get('FX_RATES_URL') or 'https://api.frankfurter.app/latest?from=EUR'
    # Every currency the ECB does not publish (PKR among them).
    fallback_url = os.environ.get('FX_FALLBACK_URL') or 'https://open.er-api.com/v6/latest/EUR'
    ttl_ms = _number('FX_TTL_MS', 12 * 60 * 60 * 1000)


class env:
    port = int(_number('PORT', 8080))

    monday = _Monday
    openai = _OpenAI
    fx = _Fx

    # Used only when the block payload carries no board id.
    default_board_id = os.environ.get('DEFAULT_BOARD_ID') or ''

    # Pause before the write, to stay under monday's per-minute complexity budget.
    board_item_delay_ms = _number('BOARD_ITEM_DELAY_MS', 0)

    # The stages enrichment may move a lead off, comma-separated. Unset means the
    # default in mapping.py ("Inbound" and the enrichment stage itself); every
    # other stage is held, so a booked discovery call is never overwritten.
    lifecycle_stage_sources = [
        label.strip() for label in (os.environ.get('LIFECYCLE_STAGE_SOURCES') or '').split(',') if label.strip()
    ]


def assert_configured():
    missing = []
    if not env.monday.api_token:
        missing.append('MONDAY_API_TOKEN')
    if not env.openai.api_key:
        missing.append('OPENAI_API_KEY')
    return missing
