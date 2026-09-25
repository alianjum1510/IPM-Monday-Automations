/**
 * Plain stdout logging - monday-code ships stdout to `mapps code:logs -t console`.
 * Message shapes are kept identical to the previous deployment so historic log
 * searches (`Action received`, `Background enrichment done`) keep matching.
 */
export const log = (...parts) => console.log(...parts);

export const logError = (...parts) => console.error(...parts);
