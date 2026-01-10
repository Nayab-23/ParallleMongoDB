"""
Intelligent Activity Manager
Tracks user status and activity log with semantic similarity-based deduplication.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

# Import OpenAI client from main to generate summaries
from main import openai_client

logger = logging.getLogger(__name__)

# Similarity thresholds
STATUS_UPDATE_THRESHOLD = 0.85  # If similarity > 85%, skip status update (still same task)
ACTIVITY_LOG_THRESHOLD = 0.75   # If similarity > 75%, skip logging (redundant activity)


def calculate_cosine_similarity(embedding1: list[float], embedding2: list[float]) -> float:
    """
    Calculate cosine similarity between two embeddings.
    Returns value between 0 (completely different) and 1 (identical).
    """
    # Check for None explicitly (not truthiness) to avoid numpy array ambiguity
    if embedding1 is None or embedding2 is None:
        return 0.0

    # Convert pgvector to list if needed
    if hasattr(embedding1, 'tolist'):
        embedding1 = embedding1.tolist()
    if hasattr(embedding2, 'tolist'):
        embedding2 = embedding2.tolist()

    # Check length explicitly
    if len(embedding1) == 0 or len(embedding2) == 0:
        return 0.0

    try:
        # Calculate cosine similarity
        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        magnitude1 = sum(a * a for a in embedding1) ** 0.5
        magnitude2 = sum(b * b for b in embedding2) ** 0.5

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)
    except Exception as e:
        logger.error(f"[Activity Manager] Similarity calculation error: {e}")
        return 0.0


def generate_activity_summary(content: str, action_type: str = "message") -> str:
    """
    Generate concise AI summary of user activity.
    Used for both current status and history entries.
    """
    text = (content or "").strip()
    if len(text) < 10:
        return text

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize the user's current activity in 5-10 words. "
                        "Be specific and actionable. Remove filler words. "
                        "Examples:\n"
                        "- 'Working on API authentication bug'\n"
                        "- 'Planning Q4 marketing strategy'\n"
                        "- 'Polishing ParallelOS UX design'\n"
                        "- 'Debugging database migration issues'"
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=20,
            temperature=0,
        )
        summary = (resp.choices[0].message.content or "").strip()
        if summary.startswith('"') and summary.endswith('"'):
            summary = summary[1:-1]
        if summary.startswith("'") and summary.endswith("'"):
            summary = summary[1:-1]
        logger.debug(f"[Activity Summary] Generated: '{summary}' from '{text[:50]}...'")
        return summary or text
    except Exception as e:
        logger.error(f"[Activity Summary] AI generation failed: {e}")
        return text[:77] + "..." if len(text) > 80 else text


async def update_user_activity(
    user_id: str,
    content: str,
    room_id: Optional[str],
    action_type: str = "message",
    tool: str = "chat",
    db: Session = None
) -> Tuple[bool, bool, Optional["UserAction"]]:
    """
    Smart activity update with semantic similarity checks.

    Returns:
        (status_updated, activity_logged, user_action): Tuple with latest action (if written)
    """
    # Import here to avoid circular dependency
    from models import UserStatus, UserAction
    from main import generate_embedding

    logger.info(f"[Activity Manager] Processing activity for user {user_id[:8]}...")

    # Step 1: Generate activity summary
    activity_summary = generate_activity_summary(content, action_type)
    logger.info(f"[Activity Manager] Generated summary: '{activity_summary}'")

    # Step 2: Generate embedding for new activity
    try:
        activity_embedding = generate_embedding(content)
        if not activity_embedding:
            logger.warning(f"[Activity Manager] Failed to generate embedding, using raw text")
            # Fallback: still process without embedding
    except Exception as e:
        logger.error(f"[Activity Manager] Embedding generation error: {e}")
        activity_embedding = None

    # Step 3: Get user's current status
    user_status = db.query(UserStatus).filter(UserStatus.user_id == user_id).first()

    status_updated = False
    activity_logged = False
    similarity_to_status = 0.0
    similarity_to_previous = 0.0

    # Step 4: Compare to current status
    if user_status and activity_embedding is not None and user_status.status_embedding is not None:
        similarity_to_status = calculate_cosine_similarity(
            activity_embedding,
            user_status.status_embedding
        )
        logger.info(f"[Activity Manager] Similarity to current status: {similarity_to_status:.2f}")

        if similarity_to_status >= STATUS_UPDATE_THRESHOLD:
            logger.info(
                f"[Activity Manager] Activity similar to status ({similarity_to_status:.2f} >= {STATUS_UPDATE_THRESHOLD}), "
                f"skipping status update"
            )
            # Still doing the same thing - no status update needed
        else:
            # Different activity - update status
            user_status.current_status = activity_summary
            user_status.status_embedding = activity_embedding
            user_status.raw_activity_text = content
            user_status.room_id = room_id
            user_status.last_updated = datetime.now(timezone.utc)
            status_updated = True
            logger.info(f"[Activity Manager] Status updated (similarity: {similarity_to_status:.2f})")

    elif not user_status:
        # First time - create status
        user_status = UserStatus(
            user_id=user_id,
            current_status=activity_summary,
            status_embedding=activity_embedding,
            raw_activity_text=content,
            room_id=room_id,
            last_updated=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc)
        )
        db.add(user_status)
        status_updated = True
        logger.info(f"[Activity Manager] Created initial status for user")

    # Step 5: Similarity to recent (for observability only; do not skip logging)
    recent_activities = db.query(UserAction).filter(
        UserAction.user_id == user_id,
        UserAction.activity_embedding.isnot(None)
    ).order_by(desc(UserAction.timestamp)).limit(3).all()

    max_similarity_to_recent = 0.0
    if activity_embedding is not None and recent_activities:
        for recent in recent_activities:
            if recent.activity_embedding is not None:
                sim = calculate_cosine_similarity(activity_embedding, recent.activity_embedding)
                max_similarity_to_recent = max(max_similarity_to_recent, sim)

        similarity_to_previous = max_similarity_to_recent
        logger.info(f"[Activity Manager] Max similarity to recent activities: {max_similarity_to_recent:.2f}")

    # Step 6: Always log the activity (append-only), but include status/embedding metadata
    if not room_id:
        logger.warning("[Activity Manager] Missing room_id for user_action user_id=%s", user_id)

    user_action = UserAction(
        user_id=user_id,
        timestamp=datetime.now(timezone.utc),
        tool=tool,
        action_type=action_type,
        action_data={"content": content, "room_id": room_id},
        activity_summary=activity_summary,
        activity_embedding=activity_embedding,
        similarity_to_status=similarity_to_status,
        similarity_to_previous=similarity_to_previous,
        is_status_change=status_updated,
        room_id=room_id
    )
    db.add(user_action)
    activity_logged = True
    logger.info(
        "[UserActionWrite] user_id=%s room_id=%s tool=%s action_type=%s is_status_change=%s embedding=%s",
        user_id,
        room_id,
        tool,
        action_type,
        status_updated,
        1 if activity_embedding is not None else 0,
    )

    db.commit()

    return (status_updated, activity_logged, user_action)
