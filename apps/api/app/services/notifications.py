import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from config import openai_client
from models import (
    User as UserORM,
    RoomMember as RoomMemberORM,
    Notification as NotificationORM,
    Message as MessageORM,
    UserCanonicalPlan,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_recent_user_messages(user_id: str, db: Session, limit: int = 20):
    """
    Get a user's recent messages across chats for context-aware notifications.
    """
    messages = (
        db.query(MessageORM)
        .filter(
            MessageORM.sender_id == f"user:{user_id}",
            MessageORM.role == "user",
        )
        .order_by(MessageORM.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }
        for msg in messages
    ]


def check_activity_relevance(activity_description: str, user_context: str) -> dict:
    """
    Quick GPT-4o-mini call to check if activity is relevant to a user's work.
    """
    prompt = f"""
User's recent work context (last 20 messages):
{(user_context or '')[:500]}

Team activity:
{activity_description}

Is this activity relevant to the user's current work?

Reply ONLY with valid JSON (no markdown):
{{"relevant": true/false, "score": 0.0-1.0, "reason": "brief explanation"}}
"""
    if not openai_client:
        return {"relevant": True, "score": 0.5, "reason": "LLM unavailable"}
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You determine if team activity is relevant to a user's work. Reply ONLY with JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=100,
            temperature=0.3,
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        logger.error(f"[Relevance Check] Failed: {e}")
        return {"relevant": True, "score": 0.5, "reason": "Could not determine relevance"}


def create_smart_team_update(actor_user_id: str, room_id: str, update_type: str, description: str, db: Session):
    """
    Context-aware team notifications to reduce spam.
    """
    actor = db.get(UserORM, actor_user_id)
    if not actor:
        logger.warning(f"[Smart Notification] Actor {actor_user_id} not found")
        return

    member_ids = [
        m.user_id
        for m in db.query(RoomMemberORM)
        .filter(
            RoomMemberORM.room_id == room_id,
            RoomMemberORM.user_id != actor_user_id,
        )
        .all()
    ]

    notified_any = False
    for member_id in member_ids:
        recent_messages = get_recent_user_messages(member_id, db=db, limit=20)
        context_text = "\n".join([(m.get("content") or "")[:100] for m in recent_messages])
        relevance = check_activity_relevance(description, context_text)
        try:
            score = float(relevance.get("score", 0))
        except Exception:
            score = 0.0
        should_notify = bool(relevance.get("relevant")) or score > 0.6

        if should_notify:
            notif = NotificationORM(
                id=str(uuid.uuid4()),
                user_id=member_id,
                type="team_update",
                title="Team update",
                message=f"{actor.name} {description} - {relevance.get('reason', '')}".strip(),
                data={
                    "update_type": update_type,
                    "actor_id": actor_user_id,
                    "score": score,
                    "relevant": relevance.get("relevant", True),
                },
                is_read=False,
                created_at=datetime.now(timezone.utc),
            )
            db.add(notif)
            notified_any = True
        logger.info(f"[Smart Notification] {actor_user_id} -> {member_id}: relevance={score:.2f}, notified={should_notify}")

    if notified_any:
        db.commit()


def create_timeline_reminders(db: Session):
    """Send reminders for timeline items with upcoming deadlines."""
    now = datetime.utcnow()
    two_hours_from_now = now + timedelta(hours=2)

    users_with_plans = db.query(UserORM, UserCanonicalPlan).join(
        UserCanonicalPlan, UserORM.id == UserCanonicalPlan.user_id
    ).all()

    for user, plan in users_with_plans:
        if not plan.approved_timeline:
            continue

        daily_goals = plan.approved_timeline.get("1d", [])

        for goal in daily_goals:
            deadline_str = goal.get("deadline_raw")
            if not deadline_str:
                continue

            try:
                deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            except Exception:
                continue

            if not (now < deadline < two_hours_from_now):
                continue

            existing = db.query(NotificationORM).filter(
                NotificationORM.user_id == user.id,
                NotificationORM.type == "timeline_reminder",
                NotificationORM.data.contains({"goal_id": goal.get("id")})
            ).first()

            if existing:
                continue

            hours_until = (deadline - now).total_seconds() / 3600
            notification = NotificationORM(
                id=str(uuid.uuid4()),
                user_id=user.id,
                type="timeline_reminder",
                severity="medium",
                title=f"Upcoming: {goal.get('text', 'Task')[:50]}",
                message=f"You have '{goal.get('text')}' in {hours_until:.1f} hours. Are you prepared?",
                source_type="timeline",
                created_at=now,
                is_read=False,
                data={"goal_id": goal.get("id"), "deadline": deadline_str}
            )
            db.add(notification)

    db.commit()
