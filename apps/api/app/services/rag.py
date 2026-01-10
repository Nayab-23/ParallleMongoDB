import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from config import openai_client
from models import Message as MessageORM

logger = logging.getLogger(__name__)


def generate_embedding(content: str) -> List[float]:
    if openai_client is None:
        raise RuntimeError("OpenAI client not configured; cannot generate embeddings")

    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=content[:8000],
    )
    return response.data[0].embedding


def _fallback_recent_messages(
    db: Session,
    room_id: str,
    *,
    limit: int,
    max_age_days: Optional[int],
) -> List[MessageORM]:
    query = db.query(MessageORM).filter(MessageORM.room_id == room_id)
    if max_age_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        query = query.filter(MessageORM.created_at >= cutoff)
    rows = (
        query.order_by(MessageORM.created_at.desc(), MessageORM.id.desc())
        .limit(limit)
        .all()
    )
    for row in rows:
        setattr(row, "kind", "message")
        setattr(row, "score", 0.0)
    return rows


def get_relevant_context(
    db: Session,
    query: str,
    *,
    room_id: Optional[str] = None,
    room_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    viewer_room_ids: Optional[List[str]] = None,
    limit: int = 10,
    similarity_threshold: float = 0.7,
    max_age_days: Optional[int] = 90,
) -> Dict[str, Any]:
    settings = get_settings()
    viewer_rooms = viewer_room_ids or []
    target_rooms = room_ids or ([room_id] if room_id else [])
    if not viewer_rooms:
        return {"messages": [], "timeline": None, "room_members": [], "recent_activity": []}

    if not (settings.rag_enabled and settings.is_postgres and openai_client):
        fallback_room = target_rooms[0] if target_rooms else viewer_rooms[0]
        messages = _fallback_recent_messages(db, fallback_room, limit=limit, max_age_days=max_age_days)
        return {"messages": messages, "timeline": None, "room_members": [], "recent_activity": []}

    try:
        query_embedding = generate_embedding(query)
    except Exception as exc:
        logger.warning("Semantic embedding generation failed (%s); falling back to recency search", exc)
        messages = _fallback_recent_messages(db, target_rooms[0], limit=limit, max_age_days=max_age_days)
        return {"messages": messages, "timeline": None, "room_members": [], "recent_activity": []}

    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

    time_filter = "AND created_at >= :cutoff" if max_age_days else ""

    room_restriction = ""
    if target_rooms:
        room_restriction = "AND room_id = ANY(:target_room_ids)"

    sql = text(
        f"""
        SELECT 
            id,
            1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity,
            visible_room_ids
        FROM messages
        WHERE 
            embedding IS NOT NULL
            AND (
                (visible_room_ids IS NOT NULL AND cardinality(visible_room_ids) > 0 AND visible_room_ids && :viewer_room_ids)
                OR
                ((visible_room_ids IS NULL OR cardinality(visible_room_ids)=0) AND room_id = ANY(:viewer_room_ids))
            )
            {room_restriction}
            AND 1 - (embedding <=> CAST(:query_embedding AS vector)) > :threshold
            {time_filter}
        ORDER BY similarity DESC
        LIMIT :limit
    """
    )

    params = {
        "query_embedding": embedding_str,
        "viewer_room_ids": viewer_rooms,
        "target_room_ids": target_rooms or viewer_rooms,
        "threshold": similarity_threshold,
        "limit": limit,
    }
    if max_age_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        params["cutoff"] = cutoff

    try:
        result = db.execute(sql, params)
        rows = result.fetchall()
    except Exception as exc:
        logger.error("RAG retrieval failed: %s", exc)
        fallback_room = target_rooms[0] if target_rooms else viewer_rooms[0]
        messages = _fallback_recent_messages(db, fallback_room, limit=limit, max_age_days=max_age_days)
        return {"messages": messages, "timeline": None, "room_members": [], "recent_activity": []}

    if not rows:
        return {"messages": [], "timeline": None, "room_members": [], "recent_activity": []}

    seen_ids = set()
    ordered_ids: List[str] = []
    scores: dict[str, float] = {}
    legacy_visible_used = 0
    for row in rows:
        mid = row[0]
        score = float(row[1] or 0.0)
        visible = row[2] if len(row) > 2 else None
        if not visible:
            legacy_visible_used += 1
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        ordered_ids.append(mid)
        scores[mid] = score

    messages = db.query(MessageORM).filter(MessageORM.id.in_(ordered_ids)).all()
    id_to_message = {msg.id: msg for msg in messages}

    sorted_messages: List[MessageORM] = []
    for mid in ordered_ids:
        msg = id_to_message.get(mid)
        if not msg:
            continue
        setattr(msg, "score", scores.get(mid, 0.0))
        setattr(msg, "kind", "message")
        sorted_messages.append(msg)

    logger.info("RAG retrieved %d relevant messages legacy_visible_used=%d", len(sorted_messages), legacy_visible_used)

    timeline_ctx = None
    room_members_info: List[dict] = []
    recent_activity_entries: List[dict] = []

    if user_id:
        from models import UserCanonicalPlan, User, RoomMember, UserAction

        plan = db.query(UserCanonicalPlan).filter(UserCanonicalPlan.user_id == user_id).first()
        if plan and plan.approved_timeline:
            tl = plan.approved_timeline or {}
            timeline_ctx = {
                "daily_goals": tl.get("1d", {}),
                "weekly_focus": tl.get("7d", {}),
                "monthly_objectives": tl.get("28d", {}),
            }

        member_rows = (
            db.query(User)
            .join(RoomMember, RoomMember.user_id == User.id)
            .filter(RoomMember.room_id.in_(target_rooms), User.id != user_id)
            .all()
        )
        room_members_info = [
            {"id": u.id, "name": u.name, "email": u.email}
            for u in member_rows
        ]

        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent_activity = (
            db.query(UserAction)
            .filter(
                UserAction.user_id.in_([u.id for u in member_rows]),
                UserAction.timestamp >= seven_days_ago,
            )
            .order_by(UserAction.timestamp.desc())
            .limit(50)
            .all()
        )
        for act in recent_activity:
            recent_activity_entries.append(
                {
                    "id": act.id,
                    "user_id": act.user_id,
                    "timestamp": act.timestamp.isoformat() if act.timestamp else None,
                    "tool": act.tool,
                    "action_type": act.action_type,
                    "summary": act.activity_summary or str(act.action_data)[:200],
                }
            )

    return {
        "messages": sorted_messages,
        "timeline": timeline_ctx,
        "room_members": room_members_info,
        "recent_activity": recent_activity_entries,
    }


def build_rag_context(
    messages: List[MessageORM],
    current_user_name: str,
    *,
    timeline: Optional[dict] = None,
    room_members: Optional[List[dict]] = None,
    recent_activity: Optional[List[dict]] = None,
) -> str:
    context_parts = [f"You are assisting {current_user_name}.\n"]

    if timeline:
        context_parts.append("CURRENT USER'S GOALS:")
        context_parts.append(f"Today (1d): {timeline.get('daily_goals')}")
        context_parts.append(f"This Week (7d): {timeline.get('weekly_focus')}")
        context_parts.append(f"This Month (28d): {timeline.get('monthly_objectives')}\n")

    if room_members:
        names = [m.get("name") or m.get("email") for m in room_members if m]
        context_parts.append(f"TEAM MEMBERS in current room(s): {', '.join(names)}\n")

    if recent_activity:
        context_parts.append("RECENT TEAM ACTIVITY (last 7d):")
        for act in recent_activity[:10]:
            user_label = act.get("user_id")
            context_parts.append(f"- [{user_label}] {act.get('summary')}")
        context_parts.append("")

    if messages:
        context_parts.append("=== RELEVANT PAST CONTEXT ===")
        for msg in messages:
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else ""
            context_parts.append(f"[{timestamp}] {msg.sender_name}: {msg.content}")
        context_parts.append("=== END CONTEXT ===")

    return "\n".join(context_parts)
