"""
vendor_search: monday.com Automation Block (action)
  "Vendor Search for {Item} in {Board}"
on the Vendor Mining Board, added to "When an item is created".

  POST /vendor-search

Block input fields (Developer Center):
  itemId   required
  boardId  required

The search takes minutes and monday does not wait that long, so the route
answers at once and the search runs on (service.start). Whether an item is a
request to search - group, Search Source - is decided by the run, which reads
the item itself.
"""
import logging

from fastapi import Request

from app.core.blocks import OK, field, monday_error
from app.core.features import Feature, feature_router

from . import service, settings
from .schemas import BlockOutput, MondayError

log = logging.getLogger('vendor_search')

NAME = 'vendor_search'

router = feature_router(NAME, settings.REQUIRED_SETTINGS)
RESPONSES = {400: {'model': MondayError}}


@router.post('/vendor-search', response_model=BlockOutput, responses=RESPONSES)
@router.post('/vendor-search/', response_model=BlockOutput, include_in_schema=False)
async def vendor_search(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return monday_error('Malformed request', 'The request body is not valid JSON.')

    payload = body.get('payload') if isinstance(body, dict) else None
    payload = payload if isinstance(payload, dict) else {}
    # Automation blocks (monday workflows) send `inputFields`; the legacy sentence builder `inboundFieldValues`.
    fields = payload.get('inputFields') or payload.get('inboundFieldValues') or {}
    fields = fields if isinstance(fields, dict) else {}

    try:
        board_id = int(field(fields, 'boardId'))
        item_id = int(field(fields, 'itemId'))
    except (TypeError, ValueError):
        return monday_error('Missing input', f'Board and item are required. Got: {fields}')

    log.info(f'Vendor search requested: board {board_id}, item {item_id}',
             extra={'payload': {'board_id': str(board_id), 'item_id': str(item_id)}})
    service.start(board_id, item_id)
    return OK


FEATURE = Feature(
    name=NAME,
    router=router,
    required_settings=settings.REQUIRED_SETTINGS,
    optional_settings=settings.OPTIONAL_SETTINGS,
)
