from fastapi import APIRouter

from app.api.v1 import (
    auth,
    bootstrap,
    chats,
    code_events,
    compatibility,
    context,
    debug,
    events,
    extension,
    rag,
    sync,
    tasks,
    workspaces,
    vscode,
    org_graph,
    notifications,
    timeline,
)

router = APIRouter(prefix="/api/v1")

router.include_router(auth.router, tags=["v1-auth"])
router.include_router(bootstrap.router, tags=["v1-bootstrap"])
router.include_router(compatibility.router, tags=["v1-compatibility"])
router.include_router(workspaces.router, tags=["v1-workspaces"])
router.include_router(chats.router, tags=["v1-chats"])
router.include_router(tasks.router, tags=["v1-tasks"])
router.include_router(context.router, tags=["v1-context"])
router.include_router(sync.router, tags=["v1-sync"])
router.include_router(rag.router, tags=["v1-rag"])
router.include_router(events.router, tags=["v1-events"])
router.include_router(vscode.router, tags=["v1-vscode"])
router.include_router(extension.router, tags=["v1-extension"])
router.include_router(code_events.router, tags=["v1-code-events"])
router.include_router(org_graph.router, tags=["v1-org-graph"])
router.include_router(notifications.router, tags=["notifications"])
router.include_router(timeline.router, tags=["timeline"])
router.include_router(debug.router, tags=["v1-debug"], prefix="/debug")
