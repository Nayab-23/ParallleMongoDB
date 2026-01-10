from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, require_scope, require_workspace_member
from app.services.rag import get_relevant_context
from models import User

router = APIRouter()


class RAGSearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 8
    room_id: Optional[str] = None
    filters: Optional[Dict] = None


class RAGChunk(BaseModel):
    source_id: str
    source_type: str
    text: str
    score: float
    metadata: Dict = {}


@router.post("/workspaces/{workspace_id}/rag/search", response_model=List[RAGChunk])
def rag_search(
    workspace_id: str,
    payload: RAGSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("read")),
):
    require_workspace_member(workspace_id, current_user, db)
    if not payload.query:
        raise HTTPException(status_code=422, detail="Query is required")

    ctx = get_relevant_context(
        db=db,
        query=payload.query,
        room_id=payload.room_id or workspace_id,
        user_id=current_user.id,
        limit=payload.top_k or 8,
    )

    messages = ctx.get("messages", []) if isinstance(ctx, dict) else ctx
    results: List[RAGChunk] = []
    for item in messages:
        results.append(
            RAGChunk(
                source_id=item.id,
                source_type=getattr(item, "kind", "message"),
                text=item.content,
                score=float(getattr(item, "score", 0.0) or 0.0),
                metadata={},  # metadata_json doesn't exist in DB
            )
        )
    return results
