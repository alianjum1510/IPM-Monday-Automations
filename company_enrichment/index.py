import json
import logging
import threading

from flask import Flask, request
from waitress import serve

from src.config.boards import describe_board
from src.config.env import assert_configured, env
from src.lib.logger import log, log_error
from src.services.enrichment import enrich_item
from src.services.monday import GraphQLError

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024


@app.post('/')
def action():
    """
    The action block posts here.

    monday's integration runner times the action out after a few seconds, while
    the research takes minutes - so the request is acked immediately and the work
    continues on a background thread. Every outcome is logged; nothing is
    reported back to monday, which is why the block declares no outbound fields.
    """
    log('Incoming POST /')

    ids = extract_ids(request.get_json(silent=True))
    board_id, item_id = ids['boardId'], ids['itemId']
    log(f'Action received: boardId={board_id}, itemId={item_id}', board_id=board_id, item_id=item_id)

    resolved_board_id = board_id or env.default_board_id
    log(f'Resolved IDs: boardId={resolved_board_id}, itemId={item_id}', board_id=resolved_board_id, item_id=item_id)
    if resolved_board_id:
        log(f'Board: {describe_board(resolved_board_id)}', board_id=resolved_board_id)

    if not resolved_board_id or not item_id:
        return {'error': 'boardId and itemId are required'}, 400

    threading.Thread(target=run_enrichment, args=(resolved_board_id, item_id), daemon=True).start()

    return {'received': True, 'boardId': resolved_board_id, 'itemId': item_id}, 200


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


@app.get('/', defaults={'path': ''})
@app.get('/<path:path>')
def health(path):
    """monday-code health checks and anything else. Matches the old deployment."""
    return 'OK', 200, {'Content-Type': 'text/plain; charset=utf-8'}


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


if __name__ == '__main__':
    # Run on its own, outside main.py's logging: plain lines on stdout.
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    missing = assert_configured()
    if missing:
        log_error(f"Missing environment variables: {', '.join(missing)}")

    log(f'Company Enrichment running on port {env.port}')
    # waitress is a production WSGI server; its threads keep the ack fast while
    # enrichment threads run alongside them.
    serve(app, host='0.0.0.0', port=env.port)
