import express from 'express';
import { env, assertConfigured } from './src/config/env.js';
import { log, logError } from './src/lib/logger.js';
import { enrichItem } from './src/services/enrichment.js';

const app = express();
app.use(express.json({ limit: '1mb' }));

/**
 * The action block posts here.
 *
 * monday's integration runner times the action out after a few seconds, while
 * the research takes minutes - so the request is acked immediately and the work
 * continues detached. Every outcome is logged; nothing is reported back to
 * monday, which is why the block declares no outbound fields.
 */
app.post('/', (req, res) => {
  log('Incoming POST /');

  const { boardId, itemId } = extractIds(req.body);
  log(`Action received: boardId=${boardId}, itemId=${itemId}`);

  const resolvedBoardId = boardId || env.defaultBoardId;
  log(`Resolved IDs: boardId=${resolvedBoardId}, itemId=${itemId}`);

  if (!resolvedBoardId || !itemId) {
    res.status(400).json({ error: 'boardId and itemId are required' });
    return;
  }

  res.status(200).json({ received: true, boardId: resolvedBoardId, itemId });

  enrichItem(resolvedBoardId, itemId)
    .then((result) => log(`Background enrichment done: ${JSON.stringify(result)}`))
    .catch((error) => {
      const detail = error.graphQLErrors ? JSON.stringify(error.graphQLErrors) : error.message;
      logError(`Background enrichment error: ${detail}`);
    });
});

/** monday-code health checks and anything else. Matches the old deployment. */
app.get('*', (_req, res) => res.type('text/plain').send('OK'));

/**
 * The block sends its inbound fields under payload.inputFields; the other
 * shapes are what monday's older recipe runner and manual curl tests send.
 */
function extractIds(body = {}) {
  const payload = body.payload || body;
  const input = payload.inputFields || payload.inboundFieldValues || payload;

  const boardId = input.boardId ?? input.board_id ?? payload.boardId ?? body.boardId ?? '';
  const itemId = input.itemId ?? input.item_id ?? input.pulseId ?? payload.itemId ?? body.itemId ?? '';

  return { boardId: boardId ? String(boardId) : '', itemId: itemId ? String(itemId) : '' };
}

const missing = assertConfigured();
if (missing.length) logError(`Missing environment variables: ${missing.join(', ')}`);

app.listen(env.port, () => log(`Company Enrichment running on port ${env.port}`));
