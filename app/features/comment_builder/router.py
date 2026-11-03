"""
comment_builder: monday.com Item View "Comment Builder" - log a comment on a
deal, with Write with AI, Summarize and Autofill.

  GET  /comment-builder              the page (the Item View's route); any sub-path without
                                     a file extension is the page too
  GET  /assets/<file>                its scripts and styles (index.html asks for /assets/...)
  POST /api/ai/write                 { prompt }              -> { text }
  POST /api/ai/summarize             { text }                -> { text }
  POST /api/ai/autofill              { comment, options, …}  -> { fields }
  POST /api/files/upload?updateId=&itemId=&name=   body: the file  -> { id, name, url }
  GET  /comment-builder/health       which secrets were found, and where (never a value)

The page and its assets are public: monday's iframe loads them with no token.
Every /api call carries monday's session token (app/core/security.py), and
every failure answers {"error": ...}, which the page shows.

/assets and /api are at the root because the built page (static/) calls
them by absolute path; moving them under /comment-builder means rebuilding the
page (see README.md).
"""
import json
import logging
import os
import re

from fastapi import Request, Response
from fastapi.concurrency import run_in_threadpool

from app.core import config
from app.core.features import Feature, view_api, view_router
from app.core.security import SESSION_SETTINGS
from app.core.views import ViewError, view_error

from . import files, service
from .ratelimit import rate_limit
from .schemas import (
    AutofillRequest,
    AutofillResponse,
    FileResponse,
    SummarizeRequest,
    TextResponse,
    ViewErrorResponse,
    WriteRequest,
)

NAME = 'comment_builder'
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
MAX_BODY = 64 * 1024
MAX_FILE = 25 * 1024 * 1024  # the page's limit too (updates-feed.js DCL_MAX_FILE_BYTES)
CONTENT_TYPE = re.compile(r'[\w.+-]{1,64}/[\w.+-]{1,128}')
UPLOAD_SETTINGS = {'MONDAY_API_TOKEN': ('MONDAY_API_TOKEN', 'MONDAY_API_KEY')}

log = logging.getLogger(NAME)

TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.ico': 'image/x-icon',
    '.json': 'application/json',
}

router = view_router(NAME)
API = view_api(NAME, service.REQUIRED_SETTINGS)
UPLOAD_API = view_api(NAME, UPLOAD_SETTINGS)  # uploads need no OpenAI key, but the monday token
ERRORS = {code: {'model': ViewErrorResponse} for code in (400, 401, 403, 404, 413, 429, 500, 502)}


# ---------- the AI actions ----------


@router.post('/api/ai/write', dependencies=API, response_model=TextResponse, responses=ERRORS,
             openapi_extra={'requestBody': {'content': {'application/json': {'schema': WriteRequest.model_json_schema()}}}})
async def write(request: Request):
    body = await guarded_body(request)
    prompt = service.js_str(body.get('prompt') or '').strip()[:4000]
    if not prompt:
        raise ViewError(400, 'Describe what the update should say.')
    return {'text': await run_in_threadpool(service.write, prompt)}


@router.post('/api/ai/autofill', dependencies=API, response_model=AutofillResponse, responses=ERRORS,
             openapi_extra={'requestBody': {'content': {'application/json': {'schema': AutofillRequest.model_json_schema()}}}})
async def autofill(request: Request):
    body = await guarded_body(request)
    if not service.js_str(body.get('comment') or '').strip():
        raise ViewError(400, 'Write the comment first.')
    return {'fields': await run_in_threadpool(service.autofill, body)}


@router.post('/api/ai/summarize', dependencies=API, response_model=TextResponse, responses=ERRORS,
             openapi_extra={'requestBody': {'content': {'application/json': {'schema': SummarizeRequest.model_json_schema()}}}})
async def summarize(request: Request):
    body = await guarded_body(request)
    text = service.js_str(body.get('text') or '').strip()[:12000]
    if not text:
        raise ViewError(400, 'This update has no text to summarize.')
    return {'text': await run_in_threadpool(service.summarize, text)}


# ---------- 📎 files from the computer ----------


@router.post('/api/files/upload', dependencies=UPLOAD_API, response_model=FileResponse, responses=ERRORS)
async def upload(request: Request, updateId: str = '', itemId: str = '', name: str = ''):
    """The request body is the file itself; files.py checks the update is the user's, then uploads it to monday."""
    claims = getattr(request.state, 'monday_claims', {}) or {}
    if not (updateId.isdigit() and itemId.isdigit() and len(updateId) <= 20 and len(itemId) <= 20):
        raise ViewError(400, 'updateId and itemId must be monday ids.')
    file_name = files.safe_name(name)
    if not file_name:
        raise ViewError(400, 'The file has no name.')
    if not claims.get('user_id'):
        raise ViewError(401, 'The monday session has no user. Reload the page.')
    rate_limit(f"upload-user:{claims['user_id']}", 'Too many uploads. Please wait a minute.')
    if int(request.headers.get('content-length') or 0) > MAX_FILE:
        raise ViewError(413, 'The file is larger than 25 MB.')
    content = await request.body()
    if len(content) > MAX_FILE:
        raise ViewError(413, 'The file is larger than 25 MB.')
    if not content:
        raise ViewError(400, 'The file is empty.')
    content_type = request.headers.get('content-type', '').split(';')[0].strip()
    if not CONTENT_TYPE.fullmatch(content_type):
        content_type = 'application/octet-stream'

    token = await config.get_secret('MONDAY_API_TOKEN', 'MONDAY_API_KEY')
    asset = await run_in_threadpool(
        files.attach, token, itemId, updateId, claims['user_id'], file_name, content, content_type)
    log.info('File attached to update %s (%d bytes, %s)', updateId, len(content), content_type,
             extra={'payload': {'item_id': itemId, 'update_id': updateId, 'asset_id': asset['id']}})
    return asset


async def guarded_body(request: Request) -> dict:
    """Rate limit per user and per IP, then the JSON body (at most 64 KB) - in the original server's order."""
    claims = getattr(request.state, 'monday_claims', {}) or {}
    forwarded = request.headers.get('x-forwarded-for') or (request.client.host if request.client else '')
    ip = forwarded.split(',')[0].strip()
    rate_limit(f"user:{claims.get('user_id') or 'anon'}")
    rate_limit(f"ip:{ip or 'unknown'}")

    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ViewError(413, 'Request too large.')
    try:
        return service.as_dict(json.loads(raw.decode('utf-8', errors='replace') or '{}'))
    except ValueError:
        raise ViewError(400, 'Invalid JSON.')


# ---------- diagnostics ----------


@router.get('/comment-builder/health')
async def health():
    """Open after a deploy: `signatureCheck` must be "on" and both secrets found. Sources only, never a value."""
    found = {}
    for name in ('OPENAI_API_KEY', 'MONDAY_CLIENT_SECRET'):
        await config.get_secret(name)
        found[name] = [config.source(name)] if config.source(name) else []
    check = 'on' if found['MONDAY_CLIENT_SECRET'] else 'off'
    return {'ok': True, 'signatureCheck': check, 'secretsFound': found}


# ---------- the page ----------


@router.api_route('/comment-builder', methods=['GET', 'HEAD'], include_in_schema=False)
async def page(request: Request):
    return static(request, '/')


@router.api_route('/comment-builder/{rest:path}', methods=['GET', 'HEAD'], include_in_schema=False)
async def page_path(request: Request, rest: str):
    return static(request, '/' + rest)


@router.api_route('/assets/{name:path}', methods=['GET', 'HEAD'], include_in_schema=False)
async def asset(request: Request, name: str):
    return static(request, '/assets/' + name)


def read_file(path):
    with open(path, 'rb') as f:
        return f.read()


def static(request: Request, rel: str):
    """
    A file of the built page, `rel` relative to the page's root. As the original
    server did: monday may open the page on a sub-path, so an asset is found
    wherever "/assets/" appears, a path without an extension is the page, and an
    unknown file falls back to the page - except an asset, which is never
    answered with HTML.
    """
    request.state.quiet = True
    at = rel.rfind('/assets/')
    if at > 0:
        rel = rel[at:]
    if rel in ('/', '') or not os.path.splitext(rel)[1]:
        rel = '/index.html'
    file = os.path.normpath(os.path.join(STATIC_DIR, rel.lstrip('/')))
    if not file.startswith(STATIC_DIR + os.sep):
        return view_error(403, 'Forbidden')
    try:
        buf = read_file(file)
    except OSError:
        if rel.startswith('/assets/'):
            return view_error(404, 'Not found')
        try:
            html = read_file(os.path.join(STATIC_DIR, 'index.html'))
        except OSError:
            return view_error(404, 'Not found')
        return Response(html, media_type=TYPES['.html'], headers={'Cache-Control': 'no-cache'})
    ext = os.path.splitext(file)[1].lower()
    # Asset names contain a content hash, so they can be cached for a long time; the page itself can't.
    cache = 'public, max-age=31536000, immutable' if rel.startswith('/assets/') else 'no-cache'
    return Response(buf, media_type=TYPES.get(ext, 'application/octet-stream'), headers={'Cache-Control': cache})


FEATURE = Feature(
    name=NAME,
    router=router,
    required_settings=service.REQUIRED_SETTINGS,
    optional_settings=(*service.OPTIONAL_SETTINGS, *SESSION_SETTINGS, *UPLOAD_SETTINGS['MONDAY_API_TOKEN']),
    auth='session',
)
