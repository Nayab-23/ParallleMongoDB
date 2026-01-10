import os
from fastapi import APIRouter, Request
from app.api.admin.utils import admin_ok

router = APIRouter()


@router.get("/_debug_headers")
async def debug_headers(request: Request):
    git_sha = os.getenv("GIT_SHA") or "unknown"
    example = {
        "X-Admin-Backend-Revision": git_sha,
        "X-Admin-Route": request.url.path,
        "X-Admin-Handler": "_debug_headers",
        "X-Admin-Request-Id": getattr(request.state, "request_id", None),
    }
    return admin_ok(
        request=request,
        data={"backend_revision": git_sha, "example_headers": example},
        debug={"input": {"query_params": dict(request.query_params)}},
    )
