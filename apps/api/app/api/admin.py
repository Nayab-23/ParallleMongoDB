from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])

# Import timeline debug endpoints
try:
    from app.api.admin import timeline as timeline_router

    # Include timeline debug router
    router.include_router(
        timeline_router.router,
        prefix="/timeline",
        tags=["admin-timeline-debug"]
    )
except ImportError as e:
    # If import fails, continue without timeline endpoints
    import logging
    logging.warning(f"Could not import admin timeline router: {e}")
