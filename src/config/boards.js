/**
 * The boards this block runs on, by the board id the automation sends.
 *
 * Every board is enriched the same way: columns are resolved by TITLE and each
 * dropdown's options are read from that board on every run, so the original
 * and the dev copy each use their own options. This list only names the board
 * in the run log; a board missing from it is still enriched, and the log says
 * it is not a known board.
 */
export const BOARDS = {
  5100825258: { environment: 'Netgains sandbox', name: 'Warm Lead Mining Board' },
  5106281544: { environment: 'Dev sandbox', name: 'Warm Lead Mining Board (Copy)' },
  5100463291: { environment: 'Netgains sandbox', name: 'Lead Mining Board' },
};

/** "Dev sandbox - Warm Lead Mining Board (Copy)", for the run log. */
export function describeBoard(boardId) {
  const board = BOARDS[String(boardId)];
  if (board) return `${board.environment} - ${board.name}`;
  return `board ${boardId} is not in src/config/boards.js - enriching it by column titles anyway`;
}
