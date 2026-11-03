"""
One monday-code server for every automation of this monday app:

  POST /, /company-enrichment                   Company Enrichment block   app/features/company_enrichment/
  POST /customer-name-split, /monday/split-name  Split Customer Name block  app/features/customer_name_split/
  POST /vendor-name-split                        Vendor Name Split block    app/features/vendor_name_split/
  POST /address-validator/fill, /validate        Address Validator blocks   app/features/address_validator/
  GET  /comment-builder, POST /api/ai/*          Comment Builder item view  app/features/comment_builder/
  GET  /, /health                                health check

The route a block calls decides which feature runs - never the board id or a
payload field. Features are listed in app/api/router.py; everything they share
(settings, the monday JWT check, logging) is in app/core/.

  uvicorn main:app --port 8080
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import FEATURES, build_router
from app.core import config, security
from app.core.blocks import MondayBlockError, monday_block_error_handler
from app.core.logging import RequestLogMiddleware, setup_logging
from app.core.views import ViewError, view_error_handler

setup_logging()
log = logging.getLogger('monday_apps')


async def check_settings(features):
    """
    Reads every setting the features declare (process env first, then monday-code)
    and logs what is missing per feature. Logs rather than crashes, so /health
    still answers. Key names and sources only - never a value.
    """
    keys = [*security.SETTINGS, *security.SESSION_SETTINGS,
            *(key for feature in features for key in feature.setting_keys())]
    sources = await config.load(keys)
    log.info(
        f'Settings found: {len(sources)} ({", ".join(sorted(set(sources.values()))) or "none"}), '
        f'JWT audience mode: {security.audience_mode()}',
        extra={'payload': {'sources': sources, 'jwt_audience_mode': security.audience_mode()}},
    )

    for feature in features:
        missing = await config.check_required({**auth_settings(feature), **feature.required_settings})
        if missing:
            log.error(
                f"Missing environment variables ({feature.name}): {', '.join(missing)}",
                extra={'payload': {'feature': feature.name, 'missing': missing}},
            )
        else:
            log.info(f'Config OK ({feature.name})', extra={'payload': {'feature': feature.name}})


def auth_settings(feature):
    """The settings the token check of this feature's kind needs (app/core/security.py)."""
    if feature.auth == 'session':
        return security.SESSION_REQUIRED_SETTINGS
    return security.required_settings()


def create_app(features=None):
    features = FEATURES if features is None else features

    @asynccontextmanager
    async def lifespan(_):
        await check_settings(features)
        port = config.setting('PORT', default='8080')
        log.info(
            f'monday apps running on port {port}',
            extra={'payload': {'port': port, 'features': [feature.name for feature in features]}},
        )
        yield

    # redirect_slashes=False: a POST from monday is not guaranteed to follow a
    # redirect, so each feature registers its paths with and without the slash.
    api = FastAPI(title='monday apps', lifespan=lifespan, redirect_slashes=False)
    api.add_exception_handler(MondayBlockError, monday_block_error_handler)
    api.add_exception_handler(ViewError, view_error_handler)
    api.add_middleware(RequestLogMiddleware)
    api.include_router(build_router(features))
    return api


app = create_app()
