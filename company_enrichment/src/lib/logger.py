"""
The run log. Message shapes are kept identical to the previous deployment so
historic log searches (`Action received`, `Background enrichment done`) keep
matching.

Goes through Python's `logging` as the "company_enrichment" logger; the server
(main.py, monday_logging.py) sends every line to the Developer Center's Logs
page. Keyword arguments become the line's payload there:

  log(f'Item {item_id}: enriching …', item_id=item_id, board_id=board_id)
"""
import logging

_logger = logging.getLogger('company_enrichment')


def log(message, **fields):
    _logger.info(message, extra=_payload(fields))


def log_error(message, **fields):
    _logger.error(message, extra=_payload(fields))


def _payload(fields):
    return {'payload': fields} if fields else None
