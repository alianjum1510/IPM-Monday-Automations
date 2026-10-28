"""
The Company Enrichment block's routes:

  POST /                     the block's URL before the merge (the bare deployment URL)
  POST /company-enrichment   canonical

"Company Enrichment for {Item id} in {board id}" posts here. The route reads the
ids, acks, and hands the item to service.start() - the research runs on.
"""
import json

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.features import Feature, feature_router
from app.features.company_enrichment import service
from app.features.company_enrichment.config.boards import describe_board
from app.features.company_enrichment.config.env import REQUIRED_SETTINGS, SETTINGS, env
from app.features.company_enrichment.lib.logger import log
from app.features.company_enrichment.schemas import EnrichmentAck, EnrichmentRejected

NAME = 'company_enrichment'
MAX_CONTENT_LENGTH = 1024 * 1024

router = feature_router(NAME, REQUIRED_SETTINGS)


@router.post('/', response_model=EnrichmentAck, responses={400: {'model': EnrichmentRejected}})
@router.post('/company-enrichment', response_model=EnrichmentAck, responses={400: {'model': EnrichmentRejected}})
@router.post('/company-enrichment/', response_model=EnrichmentAck, include_in_schema=False)
async def action(request: Request):
    """
    monday's runner times the action out long before the research is done -
    so the request is acked immediately and the work continues on a background
    thread (service.start).
    """
    log('Incoming POST /')

    body = await request.body()
    if len(body) > MAX_CONTENT_LENGTH:
        return JSONResponse({'error': 'request body too large'}, status_code=413)

    ids = extract_ids(_json_or_none(body))
    board_id, item_id = ids['boardId'], ids['itemId']
    log(f'Action received: boardId={board_id}, itemId={item_id}', board_id=board_id, item_id=item_id)

    resolved_board_id = board_id or env.default_board_id
    log(f'Resolved IDs: boardId={resolved_board_id}, itemId={item_id}', board_id=resolved_board_id, item_id=item_id)
    if resolved_board_id:
        log(f'Board: {describe_board(resolved_board_id)}', board_id=resolved_board_id)

    if not resolved_board_id or not item_id:
        return JSONResponse({'error': 'boardId and itemId are required'}, status_code=400)

    service.start(resolved_board_id, item_id)

    return EnrichmentAck(boardId=resolved_board_id, itemId=item_id)


def _json_or_none(body):
    """Flask's get_json(silent=True): the parsed body, or None when it is not JSON."""
    try:
        return json.loads(body) if body else None
    except ValueError:
        return None


def _first(*values):
    """The first value that is not None - JavaScript's `??` chain."""
    return next((value for value in values if value is not None), None)


def _dict(value):
    return value if isinstance(value, dict) else {}


def extract_ids(body):
    """
    The block sends its inbound fields under payload.inputFields; the other
    shapes are what monday's older recipe runner and manual curl tests send.
    """
    body = _dict(body)
    payload = _dict(body.get('payload') or body)
    input_fields = _dict(payload.get('inputFields') or payload.get('inboundFieldValues') or payload)

    board_id = _first(input_fields.get('boardId'), input_fields.get('board_id'), payload.get('boardId'),
                      body.get('boardId'), '')
    item_id = _first(input_fields.get('itemId'), input_fields.get('item_id'), input_fields.get('pulseId'),
                     payload.get('itemId'), body.get('itemId'), '')

    return {'boardId': str(board_id) if board_id else '', 'itemId': str(item_id) if item_id else ''}


FEATURE = Feature(name=NAME, router=router, required_settings=REQUIRED_SETTINGS, optional_settings=SETTINGS)
