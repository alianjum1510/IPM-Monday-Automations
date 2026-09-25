/**
 * Environment for the monday-code deployment.
 *
 * These keys already exist on app 11727119 (`mapps code:env -i 11727119 -m
 * list-keys`) - env vars live on the app, not the version, so a redeployed
 * version inherits them.
 */
export const env = {
  port: Number(process.env.PORT) || 8080,

  monday: {
    apiToken: process.env.MONDAY_API_TOKEN || process.env.MONDAY_API_KEY || '',
    apiUrl: 'https://api.monday.com/v2',
    apiVersion: process.env.MONDAY_API_VERSION || '2024-10',
  },

  openai: {
    apiKey: process.env.OPENAI_API_KEY || '',
    model: process.env.OPENAI_MODEL || 'gpt-4o',
    timeoutMs: Number(process.env.OPENAI_TIMEOUT_MS) || 240000,
  },

  /** Used only when the block payload carries no board id. */
  defaultBoardId: process.env.DEFAULT_BOARD_ID || '',

  /** Pause before the write, to stay under monday's per-minute complexity budget. */
  boardItemDelayMs: Number(process.env.BOARD_ITEM_DELAY_MS) || 0,

  /**
   * The stages enrichment may move a lead off, comma-separated. Unset means the
   * default in mapping.js ("Inbound" and the enrichment stage itself); every
   * other stage is held, so a booked discovery call is never overwritten.
   */
  lifecycleStageSources: (process.env.LIFECYCLE_STAGE_SOURCES || '')
    .split(',')
    .map((label) => label.trim())
    .filter(Boolean),
};

export function assertConfigured() {
  const missing = [];
  if (!env.monday.apiToken) missing.push('MONDAY_API_TOKEN');
  if (!env.openai.apiKey) missing.push('OPENAI_API_KEY');
  return missing;
}
