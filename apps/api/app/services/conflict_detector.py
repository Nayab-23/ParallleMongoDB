"""
Conflict Detection Service
Detects file-based and semantic conflicts between user activities.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import UserAction, User as UserORM, RoomMember

logger = logging.getLogger(__name__)


def get_shared_rooms(user_a_id: str, user_b_id: str, db: Session) -> List[str]:
    """Return room IDs that both users share."""
    user_a_rooms = db.query(RoomMember.room_id).filter(
        RoomMember.user_id == user_a_id
    ).all()
    user_b_rooms = db.query(RoomMember.room_id).filter(
        RoomMember.user_id == user_b_id
    ).all()

    a_room_ids = {r[0] for r in user_a_rooms}
    b_room_ids = {r[0] for r in user_b_rooms}

    return list(a_room_ids & b_room_ids)


def cosine_similarity(emb1: list, emb2: list) -> float:
    """
    Calculate cosine similarity between two embeddings.
    Returns value between 0 (completely different) and 1 (identical).
    """
    if not emb1 or not emb2:
        return 0.0

    # Convert pgvector to list if needed
    if hasattr(emb1, 'tolist'):
        emb1 = emb1.tolist()
    if hasattr(emb2, 'tolist'):
        emb2 = emb2.tolist()

    if len(emb1) == 0 or len(emb2) == 0:
        return 0.0

    try:
        dot_product = sum(a * b for a, b in zip(emb1, emb2))
        magnitude1 = sum(a * a for a in emb1) ** 0.5
        magnitude2 = sum(b * b for b in emb2) ** 0.5

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)
    except Exception as e:
        logger.error(f"[Conflict Detector] Similarity calculation error: {e}")
        return 0.0


def find_conflicts(
    db: Session,
    activity: UserAction,
    file_conflict_window_hours: int = 24,
    semantic_similarity_threshold: float = 0.75,
    semantic_window_days: int = 7
) -> List[Dict[str, Any]]:
    """
    Detect if activity conflicts with other users' work.

    Returns list of conflict dicts:
    {
        'affected_user_id': str,
        'affected_user_name': str,
        'is_file_conflict': bool,
        'conflict_type': 'file' | 'semantic',
        'file_name': str,
        'files': List[str],
        'similarity': float,  # For semantic conflicts
        'other_activity': UserAction  # The conflicting activity
    }
    """
    conflicts = []

    # Get the user who created this activity
    activity_user = db.query(UserORM).filter_by(id=activity.user_id).first()
    activity_user_name = activity_user.name if activity_user else "Unknown User"

    # ============================================
    # Method 1: File-based Conflict Detection
    # ============================================
    # Check if activity has file information
    files = None
    if activity.action_data:
        if isinstance(activity.action_data, dict):
            files = activity.action_data.get('files', [])
            if not files and 'file_path' in activity.action_data:
                # Single file path
                files = [activity.action_data['file_path']]

    if files and len(files) > 0:
        logger.info(f"[Conflict Detector] Checking file conflicts for {len(files)} files")

        # Find other users working on same files within time window
        cutoff = datetime.now(timezone.utc) - timedelta(hours=file_conflict_window_hours)

        # Query for overlapping file activity
        # Note: This requires action_data to be JSONB and contain 'files' array
        for file_path in files:
            # Find activities with this file in their action_data
            overlapping = db.query(UserAction).filter(
                UserAction.user_id != activity.user_id,
                UserAction.timestamp >= cutoff,
                UserAction.action_data.isnot(None)
            ).all()

            # Filter in Python for file matches (more portable than JSONB operators)
            for other in overlapping:
                if not other.action_data:
                    continue

                other_files = []
                if isinstance(other.action_data, dict):
                    other_files = other.action_data.get('files', [])
                    if not other_files and 'file_path' in other.action_data:
                        other_files = [other.action_data['file_path']]

                # Check if file_path is in other_files
                if file_path in other_files:
                    other_user = db.query(UserORM).filter_by(id=other.user_id).first()
                    other_user_name = other_user.name if other_user else "Unknown User"

                    shared_rooms = get_shared_rooms(activity.user_id, other.user_id, db)
                    if not shared_rooms:
                        continue

                    conflicts.append({
                        'affected_user_id': other.user_id,
                        'affected_user_name': other_user_name,
                        'is_file_conflict': True,
                        'conflict_type': 'file',
                        'file_name': file_path.split('/')[-1],  # Just filename
                        'files': [file_path],
                        'similarity': 1.0,  # File conflict is 100% overlap
                        'other_activity': other,
                        'timestamp': other.timestamp
                    })
                    logger.info(
                        f"[Conflict Detector] File conflict: "
                        f"{activity_user_name} and {other_user_name} both working on {file_path}"
                    )

    # ============================================
    # Method 2: Semantic Conflict Detection
    # ============================================
    # Use pgvector for fast similarity search
    if activity.activity_embedding is not None:
        logger.info("[Conflict Detector] Checking semantic conflicts using embeddings")

        cutoff = datetime.now(timezone.utc) - timedelta(days=semantic_window_days)

        # Use pgvector for fast similarity search
        # Only check activities from different users in same room (if room exists)
        try:
            # Build SQL query with pgvector similarity
            embedding_str = "[" + ",".join(map(str, activity.activity_embedding)) + "]"

            sql = text("""
                SELECT
                    id,
                    user_id,
                    activity_summary,
                    timestamp,
                    1 - (activity_embedding <=> CAST(:query_embedding AS vector)) as similarity
                FROM user_actions
                WHERE
                    user_id != :user_id
                    AND activity_embedding IS NOT NULL
                    AND timestamp >= :cutoff
                    AND 1 - (activity_embedding <=> CAST(:query_embedding AS vector)) > :threshold
                ORDER BY similarity DESC
                LIMIT 10
            """)

            result = db.execute(sql, {
                "query_embedding": embedding_str,
                "user_id": activity.user_id,
                "cutoff": cutoff,
                "threshold": semantic_similarity_threshold
            })

            rows = result.fetchall()

            for row in rows:
                other_user_id = row[1]
                similarity = float(row[4])

                # Get full activity and user details
                other = db.query(UserAction).filter_by(id=row[0]).first()
                other_user = db.query(UserORM).filter_by(id=other_user_id).first()
                other_user_name = other_user.name if other_user else "Unknown User"

                shared_rooms = get_shared_rooms(activity.user_id, other_user_id, db)
                if not shared_rooms:
                    continue

                conflicts.append({
                    'affected_user_id': other_user_id,
                    'affected_user_name': other_user_name,
                    'is_file_conflict': False,
                    'conflict_type': 'semantic',
                    'file_name': 'related work',
                    'files': [],
                    'similarity': similarity,
                    'other_activity': other,
                    'timestamp': other.timestamp
                })

                logger.info(
                    f"[Conflict Detector] Semantic conflict: "
                    f"{activity_user_name} and {other_user_name} "
                    f"(similarity: {similarity:.2f})"
                )

        except Exception as e:
            logger.error(f"[Conflict Detector] Semantic search failed: {e}")

    logger.info(f"[Conflict Detector] Found {len(conflicts)} total conflicts")
    return conflicts


def detect_file_conflicts(
    db: Session,
    time_window_hours: int = 24
) -> List[Dict[str, Any]]:
    """
    Scan recent activities for file-based conflicts.
    Returns list of conflict summaries for notification creation.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)

    # Get all recent activities with file data
    activities = db.query(UserAction).filter(
        UserAction.timestamp >= cutoff,
        UserAction.action_data.isnot(None)
    ).all()

    # Group activities by file path
    from collections import defaultdict
    file_activity = defaultdict(list)

    for activity in activities:
        if not activity.action_data:
            continue

        files = []
        if isinstance(activity.action_data, dict):
            files = activity.action_data.get('files', [])
            if not files and 'file_path' in activity.action_data:
                files = [activity.action_data['file_path']]

        for file_path in files:
            file_activity[file_path].append(activity)

    # Find files with multiple users
    conflicts = []
    for file_path, activities in file_activity.items():
        user_ids = set(a.user_id for a in activities)

        if len(user_ids) >= 2:
            # Get user names
            users = db.query(UserORM).filter(UserORM.id.in_(user_ids)).all()
            user_map = {u.id: u.name for u in users}

            conflicts.append({
                'file': file_path,
                'file_name': file_path.split('/')[-1],
                'users': [user_map.get(uid, uid) for uid in user_ids],
                'user_ids': list(user_ids),
                'activities': activities,
                'activity_count': len(activities)
            })

    return conflicts


def detect_semantic_conflicts(
    db: Session,
    threshold: float = 0.85,
    time_window_days: int = 7
) -> List[Dict[str, Any]]:
    """
    Scan recent activities for semantic conflicts using embeddings.
    Returns list of conflict summaries.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=time_window_days)

    try:
        # Find pairs of similar activities from different users
        # Using pgvector self-join
        sql = text("""
            SELECT
                a1.id as id1,
                a2.id as id2,
                a1.user_id as user1,
                a2.user_id as user2,
                a1.activity_summary as summary1,
                a2.activity_summary as summary2,
                1 - (a1.activity_embedding <=> a2.activity_embedding) as similarity,
                a1.timestamp as timestamp1,
                a2.timestamp as timestamp2
            FROM user_actions a1, user_actions a2
            WHERE
                a1.user_id != a2.user_id
                AND a1.timestamp >= :cutoff
                AND a2.timestamp >= :cutoff
                AND a1.activity_embedding IS NOT NULL
                AND a2.activity_embedding IS NOT NULL
                AND a1.id < a2.id  -- Avoid duplicates
                AND 1 - (a1.activity_embedding <=> a2.activity_embedding) > :threshold
            ORDER BY similarity DESC
            LIMIT 50
        """)

        result = db.execute(sql, {
            "cutoff": cutoff,
            "threshold": threshold
        })

        rows = result.fetchall()
        conflicts = []

        # Get user names for all involved users
        user_ids = set()
        for row in rows:
            user_ids.add(row.user1)
            user_ids.add(row.user2)

        users = db.query(UserORM).filter(UserORM.id.in_(user_ids)).all()
        user_map = {u.id: u.name for u in users}

        for row in rows:
            conflicts.append({
                'users': [user_map.get(row.user1, row.user1), user_map.get(row.user2, row.user2)],
                'user_ids': [row.user1, row.user2],
                'similarity': float(row.similarity),
                'summaries': [row.summary1, row.summary2],
                'type': 'semantic_overlap',
                'activity_ids': [row.id1, row.id2]
            })

        logger.info(f"[Conflict Detector] Found {len(conflicts)} semantic conflicts")
        return conflicts

    except Exception as e:
        logger.error(f"[Conflict Detector] Semantic conflict detection failed: {e}")
        return []
