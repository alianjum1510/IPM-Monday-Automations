"""
Every feature this deployment serves. Adding one is one line here - its routes,
auth and settings come with its Feature (see app/core/features.py).
"""
from fastapi import APIRouter

from app.api import health
from app.features.company_enrichment.router import FEATURE as company_enrichment
from app.features.customer_name_split.router import FEATURE as customer_name_split
from app.features.vendor_name_split.router import FEATURE as vendor_name_split

FEATURES = [
    company_enrichment,
    customer_name_split,
    vendor_name_split,
]


def build_router(features):
    """The health check plus each feature's routes. Each feature owns its own paths."""
    router = APIRouter()
    router.include_router(health.router)
    for feature in features:
        router.include_router(feature.router)
    return router
