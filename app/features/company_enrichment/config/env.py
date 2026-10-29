"""
Environment for the monday-code deployment.

These keys already exist on app 11727119 (`mapps code:env -i 11727119 -m
list-keys`) - env vars live on the app, not the version, so a redeployed
version inherits them.

Every value is read when it is used, through app/core/config.py (process
environment first, then what the monday-code service served at startup), so
importing this module never freezes a setting.
"""
from app.core.config import setting


def _number(name, default):
    """`Number(process.env.X) || default`: unset, unparsable or 0 means the default."""
    try:
        return float(setting(name)) or default
    except ValueError:
        return default


class _Monday:
    api_url = 'https://api.monday.com/v2'

    @property
    def api_token(self):
        return setting('MONDAY_API_TOKEN', 'MONDAY_API_KEY')

    @property
    def api_version(self):
        return setting('MONDAY_API_VERSION') or '2024-10'


class _OpenAI:
    @property
    def api_key(self):
        return setting('OPENAI_API_KEY')

    @property
    def model(self):
        return setting('OPENAI_MODEL') or 'gpt-4o'

    # Optional cheaper model for the one-word country classification; defaults to `model`.
    @property
    def country_model(self):
        return setting('OPENAI_COUNTRY_MODEL')

    @property
    def timeout_ms(self):
        return _number('OPENAI_TIMEOUT_MS', 240000)


class _Fx:
    """ECB exchange rates for placing a revenue figure into the board's bands."""

    @property
    def url(self):
        return setting('FX_RATES_URL') or 'https://api.frankfurter.app/latest?from=EUR'

    # Every currency the ECB does not publish (PKR among them).
    @property
    def fallback_url(self):
        return setting('FX_FALLBACK_URL') or 'https://open.er-api.com/v6/latest/EUR'

    @property
    def ttl_ms(self):
        return _number('FX_TTL_MS', 12 * 60 * 60 * 1000)


class _Env:
    monday = _Monday()
    openai = _OpenAI()
    fx = _Fx()

    @property
    def port(self):
        return int(_number('PORT', 8080))

    # Used only when the block payload carries no board id.
    @property
    def default_board_id(self):
        return setting('DEFAULT_BOARD_ID')

    # Pause before the write, to stay under monday's per-minute complexity budget.
    @property
    def board_item_delay_ms(self):
        return _number('BOARD_ITEM_DELAY_MS', 0)

    # Where a researched name is split into Company / Customer Name (2) - the
    # same limit, and setting, as customer_name_split uses.
    @property
    def max_name_length(self):
        return int(_number('MAX_NAME_LENGTH', 100))

    # The stages enrichment may move a lead off, comma-separated. Unset means the
    # default in mapping.py ("Inbound" and the enrichment stage itself); every
    # other stage is held, so a booked discovery call is never overwritten.
    @property
    def lifecycle_stage_sources(self):
        return [label.strip() for label in setting('LIFECYCLE_STAGE_SOURCES').split(',') if label.strip()]


env = _Env()

# Every key read above, loaded from monday-code at startup. PORT is left out:
# monday-code sets it directly.
SETTINGS = (
    'MONDAY_API_TOKEN', 'MONDAY_API_KEY', 'MONDAY_API_VERSION',
    'OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_COUNTRY_MODEL', 'OPENAI_TIMEOUT_MS',
    'FX_RATES_URL', 'FX_FALLBACK_URL', 'FX_TTL_MS',
    'DEFAULT_BOARD_ID', 'BOARD_ITEM_DELAY_MS', 'LIFECYCLE_STAGE_SOURCES', 'TAXONOMY_TTL_MS', 'MAX_NAME_LENGTH',
)

# Without these a run cannot read the item or research it.
REQUIRED_SETTINGS = {
    'MONDAY_API_TOKEN': ('MONDAY_API_TOKEN', 'MONDAY_API_KEY'),
    'OPENAI_API_KEY': ('OPENAI_API_KEY',),
}
