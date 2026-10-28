"""
The day's exchange rates, quoted per 1 EUR ({USD: 1.08, PKR: 310 ...}), for
placing a researched revenue figure into the board's revenue bands.

Two free feeds, no API key:
  - the ECB reference rates (via Frankfurter) - authoritative, but only ~30
    currencies, and no PKR;
  - open.er-api.com - 160+ currencies, used for every currency the ECB does
    not publish, which is what makes a Pakistani company's PKR revenue
    convertible.
Where both quote a currency, the ECB rate wins. Both are cached for
FX_TTL_MS (default 12 hours), so a run normally costs no request at all.

There is deliberately no hard-coded fallback table: a stale rate would put a
figure near a band edge into the wrong band and look like data. When both
feeds are unreachable this returns the last rates it had, or None - a figure
already in the board's currency is still placed, and a foreign one falls back
to the band the model chose. The run log says which.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from app.features.company_enrichment.config.env import env
from app.features.company_enrichment.lib.logger import log

_cache = None


def _fetch_rates(url):
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json() or {}
        rates = data.get('rates')
        if not rates or not isinstance(rates, dict):
            raise ValueError('response carried no rates')
        return {'rates': rates, 'date': data.get('date') or str(data.get('time_last_update_utc') or '')[5:16]}
    except Exception as error:
        log(f'Could not load exchange rates from {url}: {error}')
        return None


def get_rates():
    global _cache
    if _cache and time.time() * 1000 - _cache['fetched_at'] < env.fx.ttl_ms:
        return _cache['value']

    # Both feeds at once, as neither depends on the other.
    with ThreadPoolExecutor(max_workers=2) as pool:
        ecb, wide = pool.map(_fetch_rates, [env.fx.url, env.fx.fallback_url])
    if not ecb and not wide:
        return _cache['value'] if _cache else None

    value = {
        'rates': {**((wide or {}).get('rates') or {}), **((ecb or {}).get('rates') or {}), 'EUR': 1},
        'date': (ecb or {}).get('date') or (wide or {}).get('date') or '',
    }
    _cache = {'value': value, 'fetched_at': time.time() * 1000}
    return value
