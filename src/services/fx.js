import axios from 'axios';
import { env } from '../config/env.js';
import { log } from '../lib/logger.js';

/**
 * The day's ECB reference rates, quoted per 1 EUR ({USD: 1.08, GBP: 0.85 ...}),
 * for placing a researched revenue figure into the board's revenue bands.
 *
 * Frankfurter republishes the ECB feed with no API key. The ECB publishes once
 * per working day, so the rates are cached for FX_TTL_MS (default 12 hours) and
 * a run normally costs no request at all.
 *
 * There is deliberately no hard-coded fallback table: a stale rate would put a
 * figure near a band edge into the wrong band and look like data. When the feed
 * is unreachable this returns null, a figure already in the board's currency is
 * still placed, and a foreign one falls back to the band the model chose - the
 * run log says which.
 */
let cache = null;

export async function getRates() {
  if (cache && Date.now() - cache.fetchedAt < env.fx.ttlMs) return cache.value;

  try {
    const res = await axios.get(env.fx.url, { timeout: 10000 });
    const rates = res.data?.rates;
    if (!rates || typeof rates !== 'object') throw new Error('response carried no rates');

    const value = { rates: { ...rates, EUR: 1 }, date: res.data.date || '' };
    cache = { value, fetchedAt: Date.now() };
    return value;
  } catch (error) {
    log(`Could not load exchange rates from ${env.fx.url}: ${error.message}`);
    // Keep serving yesterday's rates rather than none - they are still real ECB rates.
    return cache?.value || null;
  }
}
