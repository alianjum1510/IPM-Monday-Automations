import axios from 'axios';
import { env } from '../config/env.js';
import { log } from '../lib/logger.js';

/**
 * The day's exchange rates, quoted per 1 EUR ({USD: 1.08, PKR: 310 ...}), for
 * placing a researched revenue figure into the board's revenue bands.
 *
 * Two free feeds, no API key:
 *   - the ECB reference rates (via Frankfurter) - authoritative, but only ~30
 *     currencies, and no PKR;
 *   - open.er-api.com - 160+ currencies, used for every currency the ECB does
 *     not publish, which is what makes a Pakistani company's PKR revenue
 *     convertible.
 * Where both quote a currency, the ECB rate wins. Both are cached for
 * FX_TTL_MS (default 12 hours), so a run normally costs no request at all.
 *
 * There is deliberately no hard-coded fallback table: a stale rate would put a
 * figure near a band edge into the wrong band and look like data. When both
 * feeds are unreachable this returns the last rates it had, or null - a figure
 * already in the board's currency is still placed, and a foreign one falls back
 * to the band the model chose. The run log says which.
 */
let cache = null;

async function fetchRates(url) {
  try {
    const res = await axios.get(url, { timeout: 10000 });
    const rates = res.data?.rates;
    if (!rates || typeof rates !== 'object') throw new Error('response carried no rates');
    return { rates, date: res.data.date || String(res.data.time_last_update_utc || '').slice(5, 16) };
  } catch (error) {
    log(`Could not load exchange rates from ${url}: ${error.message}`);
    return null;
  }
}

export async function getRates() {
  if (cache && Date.now() - cache.fetchedAt < env.fx.ttlMs) return cache.value;

  const [ecb, wide] = await Promise.all([fetchRates(env.fx.url), fetchRates(env.fx.fallbackUrl)]);
  if (!ecb && !wide) return cache?.value || null;

  const value = {
    rates: { ...(wide?.rates || {}), ...(ecb?.rates || {}), EUR: 1 },
    date: ecb?.date || wide?.date || '',
  };
  cache = { value, fetchedAt: Date.now() };
  return value;
}
