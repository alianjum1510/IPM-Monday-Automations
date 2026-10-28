"""
Company Enrichment, without HTTP: start a run for one item, and the run itself.

The research takes minutes, so the route acks immediately and the run continues
on a background thread. Every outcome is logged; nothing is reported back to
monday, which is why the block declares no outbound fields.
"""
import contextvars
import json
import threading

from app.features.company_enrichment.lib.logger import log, log_error
from app.features.company_enrichment.services.enrichment import enrich_item
from app.features.company_enrichment.services.monday import GraphQLError


def start(board_id, item_id):
    """Runs the enrichment on a background thread, carrying the request's log context into it."""
    context = contextvars.copy_context()
    threading.Thread(target=context.run, args=(run_enrichment, board_id, item_id), daemon=True).start()


def run_enrichment(board_id, item_id):
    try:
        result = enrich_item(board_id, item_id)
        log(f"Background enrichment done: {json.dumps(result, separators=(',', ':'), ensure_ascii=False)}", **result)
    except GraphQLError as error:
        log_error(
            f'Background enrichment error: {json.dumps(error.graphql_errors)}',
            board_id=board_id, item_id=item_id, graphql_errors=error.graphql_errors,
        )
    except Exception as error:
        log_error(f'Background enrichment error: {error}', board_id=board_id, item_id=item_id, error=str(error))
