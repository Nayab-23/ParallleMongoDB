"""
Admin Collaboration Debug API Endpoints
Provides collaboration and notification monitoring for platform admins.
"""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
import hashlib
from database import get_db
from models import User, Message, Notification, ChatInstance, UserAction, CollaborationSignal, CollaborationAuditRun
from datetime import datetime, timedelta
from typing import List, Optional
import json
import logging
import uuid
from pydantic import BaseModel

from app.api.dependencies import require_platform_admin
from app.api.admin.utils import admin_ok, admin_fail, sanitize_for_json

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_json(value):
    if isinstance(value, dict):
        return {k: _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    return sanitize_for_json(value)


def build_interaction_graph(users, chats, notifications, conflicts):
    """Build interaction graph nodes and edges."""
    logger.debug(f"[Collab Debug] Building interaction graph for {len(users)} users")

    nodes = []
    edges = []

    # Create nodes (one per user)
    for user in users:
        # Count total activity for this user
        activity_count = 0

        # Count from notifications
        activity_count += len([n for n in notifications if n["to_user"] == user.email or n.get("from_user") == user.email])

        nodes.append({
            "id": user.email,
            "label": user.name or user.email,
            "activity_count": activity_count
        })

    # Create edges (interactions between users)
    user_pairs = {}  # Track interaction counts between pairs

    # Edges from chats
    for chat in chats:
        participants = chat["participants"]
        for i, user1 in enumerate(participants):
            for user2 in participants[i+1:]:
                pair_key = tuple(sorted([user1, user2]))
                if pair_key not in user_pairs:
                    user_pairs[pair_key] = {"chat": 0, "notification": 0, "conflict": 0}
                user_pairs[pair_key]["chat"] += chat["message_count"]

    # Edges from notifications
    for notif in notifications:
        if notif.get("from_user") and notif.get("to_user"):
            pair_key = tuple(sorted([notif["from_user"], notif["to_user"]]))
            if pair_key not in user_pairs:
                user_pairs[pair_key] = {"chat": 0, "notification": 0, "conflict": 0}
            user_pairs[pair_key]["notification"] += 1

    # Edges from conflicts
    for conflict in conflicts:
        if len(conflict["users"]) >= 2:
            pair_key = tuple(sorted(conflict["users"][:2]))
            if pair_key not in user_pairs:
                user_pairs[pair_key] = {"chat": 0, "notification": 0, "conflict": 0}
            user_pairs[pair_key]["conflict"] += 1

    # Build edge list
    for (user1, user2), counts in user_pairs.items():
        types = []
        if counts["conflict"] > 0:
            types.append("conflict")
        if counts["chat"] > 0:
            types.append("chat")
        if counts["notification"] > 0:
            types.append("notification")

        edges.append({
            "source": user1,
            "target": user2,
            "weight": counts["chat"] + counts["notification"] + counts["conflict"],
            "types": types,
            "chat_count": counts["chat"],
            "notification_count": counts["notification"],
            "conflict_count": counts["conflict"]
        })

    logger.debug(f"[Collab Debug] Graph built: {len(nodes)} nodes, {len(edges)} edges")

    return {
        "nodes": nodes,
        "edges": edges
    }


@router.get("/collaboration/messages")
async def get_collab_messages(
    user_email: str = Query(...),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    request_id = str(uuid.uuid4())
    try:
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            return admin_fail(
                request=request,
                code="NOT_FOUND",
                message="User not found",
                details={"user_email": user_email},
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=404,
            )
        messages = (
            db.query(Message)
            .filter(Message.user_id == user.id)
            .order_by(Message.created_at.desc())
            .limit(limit)
            .all()
        )
        result = [
            {
                "id": m.id,
                "ts": m.created_at.isoformat() if m.created_at else None,
                "role": m.role,
                "content": m.content,
                "thread_id": m.chat_instance_id,
            }
            for m in messages
        ]
        return admin_ok(
            request=request,
            data={"messages": result, "limit": limit},
            debug={
                "input": {"query_params": dict(request.query_params)},
                "output": {"messages_count": len(result)},
                "db": {"tables_queried": ["messages", "users"]},
            },
        )
    except Exception as exc:
        logger.exception("Failed to fetch collaboration messages", extra={"request_id": request_id})
        return admin_fail(
            request=request,
            code="COLLAB_MESSAGES_ERROR",
            message="Failed to fetch messages",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )


class BatchMessagesPayload(BaseModel):
    user_emails: List[str]
    limit: int = 20


@router.post("/collaboration/messages/batch")
async def get_collab_messages_batch(
    payload: BatchMessagesPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    request_id = str(uuid.uuid4())
    try:
        limit = max(1, min(payload.limit, 200))
        results = {}
        for email in payload.user_emails:
            user = db.query(User).filter(User.email == email).first()
            if not user:
                results[email] = {"messages": [], "error": "User not found"}
                continue
            messages = (
                db.query(Message)
                .filter(Message.user_id == user.id)
                .order_by(Message.created_at.desc())
                .limit(limit)
                .all()
            )
            results[email] = [
                {
                    "id": m.id,
                    "ts": m.created_at.isoformat() if m.created_at else None,
                    "role": m.role,
                    "content": m.content,
                    "thread_id": m.chat_instance_id,
                }
                for m in messages
            ]
        return admin_ok(
            request=request,
            data={"results": results, "limit": limit},
            debug={
                "input": {"payload": payload.dict()},
                "output": {"results_count": len(results)},
                "db": {"tables_queried": ["messages", "users"]},
            },
        )
    except Exception as exc:
        logger.exception("Failed batch collaboration messages", extra={"request_id": request_id})
        return admin_fail(
            request=request,
            code="COLLAB_MESSAGES_ERROR",
            message="Failed to fetch messages",
            details={"error": str(exc)},
            debug={"input": {"payload": getattr(payload, 'dict', lambda: {} )()}},
            status_code=500,
        )


@router.get("/collaboration-debug")
async def get_collaboration_debug(
    request: Request,
    users: List[str] = Query(..., description="List of user emails (1-4)"),
    days: int = Query(7, description="Number of days to look back"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin)
):
    """
    Get collaboration debug info for multiple users.
    Shows interactions, notifications, conflicts, and collaboration opportunities.
    Admin only.

    Frontend calls: GET /api/admin/collaboration-debug?users=user1@example.com&users=user2@example.com&days=7

    Returns:
    - Chat interactions between users
    - Notifications sent between users
    - Conflicts detected
    - Collaboration opportunities (common files/projects)
    - Interaction graph (nodes and edges)
    - Summary statistics
    """
    logger.info(f"[Collab Debug] 🔍 GET /collaboration-debug called by {current_user.email}")
    users_raw = list(users)
    if len(users_raw) == 1 and "," in users_raw[0]:
        users = [u.strip() for u in users_raw[0].split(",") if u.strip()]
    logger.info(f"[Collab Debug] Analyzing {len(users)} users: {users}")

    logger.debug(f"[Collab Debug] ✅ Admin access verified for {current_user.email}")

    # STEP 2: Validate user count
    if len(users) < 1 or len(users) > 4:
        logger.error(f"[Collab Debug] ❌ Invalid user count: {len(users)} (must be 1-4)")
        return admin_fail(
            request=request,
            code="VALIDATION_ERROR",
            message="Must select 1-4 users",
            details={"user_count": len(users)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=400,
        )

    # STEP 3: Find users
    logger.debug(f"[Collab Debug] Querying {len(users)} users...")
    user_objects = db.query(User).filter(User.email.in_(users)).all()
    if len(user_objects) != len(users):
        found_emails = [u.email for u in user_objects]
        missing = set(users) - set(found_emails)
        logger.error(f"[Collab Debug] ❌ Users not found: {missing}")
        return admin_fail(
            request=request,
            code="NOT_FOUND",
            message="Users not found",
            details={"missing": list(missing)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=404,
        )

    user_ids = [u.id for u in user_objects]
    user_map = {u.id: u.email for u in user_objects}
    logger.debug(f"[Collab Debug] ✅ Found all {len(user_objects)} users")

    # STEP 4: Date range
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    logger.info(f"[Collab Debug] Date range: {start_dt.date()} to {end_dt.date()} ({days} days)")

    # STEP 5: Get chat interactions between selected users (all interactions, no multi-user requirement)
    logger.debug(f"[Collab Debug] Querying chat interactions/messages...")
    messages = (
        db.query(Message)
        .filter(
            and_(
                Message.user_id.in_(user_ids),
                Message.created_at >= start_dt,
            )
        )
        .order_by(Message.created_at.desc())
        .all()
    )

    chat_groups = {}
    for msg in messages:
        cid = msg.chat_instance_id or msg.room_id or "unknown"
        grp = chat_groups.setdefault(
            cid,
            {
                "chat_id": cid,
                "participants": set(),
                "message_count": 0,
                "last_activity": None,
                "first_activity": None,
            },
        )
        grp["participants"].add(user_map.get(msg.user_id, str(msg.user_id)))
        grp["message_count"] += 1
        ts = msg.created_at
        if ts:
            if grp["last_activity"] is None or ts > grp["last_activity"]:
                grp["last_activity"] = ts
            if grp["first_activity"] is None or ts < grp["first_activity"]:
                grp["first_activity"] = ts

    chat_interactions = [
        {
            "chat_id": cid,
            "participants": sorted(list(data["participants"])),
            "message_count": data["message_count"],
            "last_activity": data["last_activity"].isoformat() if data["last_activity"] else None,
            "first_activity": data["first_activity"].isoformat() if data["first_activity"] else None,
        }
        for cid, data in chat_groups.items()
    ]

    logger.info(f"[Collab Debug] Found {len(chat_interactions)} chat interactions (all involving selected users)")

    # STEP 6: Get notifications between users
    logger.debug(f"[Collab Debug] Querying notifications...")
    notifications = db.query(Notification).filter(
        and_(
            Notification.user_id.in_(user_ids),
            Notification.created_at >= start_dt
        )
    ).order_by(Notification.created_at.desc()).all()

    logger.info(f"[Collab Debug] Found {len(notifications)} notifications")

    notification_list = []
    for notif in notifications:
        # Try to identify "from_user" from notification data
        from_user = None
        if notif.data and isinstance(notif.data, dict):
            from_user_id = notif.data.get('from_user_id') or notif.data.get('other_user_id')
            if from_user_id:
                from_user = user_map.get(from_user_id)

        notification_list.append({
            "id": notif.id,
            "timestamp": notif.created_at.isoformat(),
            "from_user": from_user,
            "to_user": user_map.get(notif.user_id),
            "type": notif.type,
            "severity": notif.severity,
            "source_type": notif.source_type,
            "title": notif.title,
            "message": notif.message,
            "read": notif.is_read
        })

    # STEP 7: Get conflicts (file and semantic)
    logger.debug(f"[Collab Debug] Extracting conflicts from notifications...")
    conflicts_detected = []
    conflict_notifs = [n for n in notification_list if n.get("source_type") in ['conflict_file', 'conflict_semantic']]

    logger.info(f"[Collab Debug] Found {len(conflict_notifs)} conflict notifications")

    for notif in conflict_notifs:
        # Find the actual notification object to get data
        notif_obj = next((n for n in notifications if n.id == notif["id"]), None)
        if not notif_obj:
            continue

        conflict_data = {
            "timestamp": notif["timestamp"],
            "type": "file" if notif["source_type"] == "conflict_file" else "semantic",
            "users": [notif["to_user"]],
            "notification_sent": True,
            "title": notif["title"],
            "message": notif["message"]
        }

        # Extract file or similarity info from data
        if notif_obj.data:
            if isinstance(notif_obj.data, dict):
                conflict_data["file"] = notif_obj.data.get('file') or notif_obj.data.get('file_path')
                conflict_data["similarity"] = notif_obj.data.get('similarity')

                # Add other user if present
                other_user_id = notif_obj.data.get('other_user_id')
                if other_user_id and other_user_id in user_map:
                    conflict_data["users"].append(user_map[other_user_id])

        conflicts_detected.append(conflict_data)

    # STEP 8: Find collaboration opportunities (semantic similarity between different users)
    logger.debug(f"[Collab Debug] Finding collaboration opportunities...")
    collaboration_opportunities = []

    # Get recent UserActions with summaries/embeddings
    user_actions = db.query(UserAction).filter(
        and_(
            UserAction.user_id.in_(user_ids),
            UserAction.timestamp >= start_dt,
            UserAction.is_status_change == True
        )
    ).order_by(UserAction.timestamp.desc()).limit(100).all()

    logger.debug(f"[Collab Debug] Found {len(user_actions)} user actions")

    # Group by user
    actions_by_user = {}
    for action in user_actions:
        if action.user_id not in actions_by_user:
            actions_by_user[action.user_id] = []
        actions_by_user[action.user_id].append(action)

    # Simple heuristic: find users working on similar files/projects
    for user_id_1 in user_ids:
        for user_id_2 in user_ids:
            if user_id_1 >= user_id_2:  # Avoid duplicates
                continue

            actions_1 = actions_by_user.get(user_id_1, [])
            actions_2 = actions_by_user.get(user_id_2, [])

            # Find common files/projects
            files_1 = set()
            files_2 = set()

            for action in actions_1:
                data = action.action_data
                if data and not isinstance(data, dict):
                    try:
                        data = json.loads(data)
                    except Exception:
                        data = None
                if data and isinstance(data, dict):
                    if 'file_path' in data:
                        files_1.add(data['file_path'])
                    if 'files' in data and isinstance(data['files'], list):
                        files_1.update(data['files'])

            for action in actions_2:
                data = action.action_data
                if data and not isinstance(data, dict):
                    try:
                        data = json.loads(data)
                    except Exception:
                        data = None
                if data and isinstance(data, dict):
                    if 'file_path' in data:
                        files_2.add(data['file_path'])
                    if 'files' in data and isinstance(data['files'], list):
                        files_2.update(data['files'])

            common_files = files_1.intersection(files_2)

            if common_files:
                similarity_score = len(common_files) / max(len(files_1), len(files_2), 1)
                logger.debug(f"[Collab Debug] Collaboration opportunity: {user_map[user_id_1]} & {user_map[user_id_2]} - {len(common_files)} common files")

                collaboration_opportunities.append({
                    "timestamp": datetime.now().isoformat(),
                    "type": "common_files",
                    "similarity_score": similarity_score,
                    "user1": user_map[user_id_1],
                    "user2": user_map[user_id_2],
                    "user1_activity": f"Working on {len(files_1)} files",
                    "user2_activity": f"Working on {len(files_2)} files",
                    "suggestion": f"Both working on: {', '.join(list(common_files)[:3])}",
                    "common_files": list(common_files)
                })

    logger.info(f"[Collab Debug] Found {len(collaboration_opportunities)} collaboration opportunities")

    # STEP 9: Build interaction graph
    logger.debug(f"[Collab Debug] Building interaction graph...")
    interaction_graph = build_interaction_graph(
        user_objects,
        chat_interactions,
        notification_list,
        conflicts_detected
    )

    # STEP 10: Build response
    response = {
        "users": users,
        "date_range": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "days": days
        },
        "chat_interactions": chat_interactions,
        "notifications": notification_list,
        "conflicts_detected": conflicts_detected,
        "collaboration_opportunities": collaboration_opportunities,
        "interaction_graph": interaction_graph,
        "summary": {
            "total_chats": len(chat_interactions),
            "total_messages": sum([c["message_count"] for c in chat_interactions]),
            "total_notifications": len(notification_list),
            "total_conflicts": len(conflicts_detected),
            "total_opportunities": len(collaboration_opportunities)
        }
    }

    logger.info(f"[Collab Debug] ✅ Returning collaboration debug data: {response['summary']}")
    try:
        return admin_ok(
            request=request,
            data=_safe_json(response),
            debug={
                "input": {
                    "query_params": dict(request.query_params),
                    "users_received": list(users),
                    "users_resolved": len(user_objects),
                    "user_ids": user_ids,
                    "cutoff_timestamp": start_dt.isoformat(),
                },
                "output": response.get("summary", {}),
                "db": {
                    "tables_queried": [
                        "users",
                        "messages",
                        "notifications",
                        "chat_instances",
                        "user_actions",
                    ]
                },
                "diagnostic": {
                    "messages_found_count": len(messages),
                    "chats_found_count": len(chat_interactions),
                }
            },
        )
    except Exception as exc:
        logger.exception("Failed to return collaboration debug data", exc_info=True)
        return admin_fail(
            request=request,
            code="COLLAB_DEBUG_ERROR",
            message="Failed to fetch collaboration debug data",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )


@router.post("/collaboration-audit/run")
async def run_collaboration_audit(
    request: Request,
    users: Optional[List[str]] = Query(default=None, description="Filter to specific user emails"),
    days: int = Query(7, ge=1, le=90),
    persist: bool = Query(False),
    include_notifications: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Recompute collaboration signals from messages and compare with notifications.
    """
    request_id = str(uuid.uuid4())
    try:
        window_end = datetime.utcnow()
        window_start = window_end - timedelta(days=days)
        user_map = {}
        if users:
            user_rows = db.query(User).filter(User.email.in_(users)).all()
            user_map = {u.id: u for u in user_rows}
            target_user_ids = set(user_map.keys())
        else:
            target_user_ids = None

        msg_query = db.query(Message).filter(Message.created_at >= window_start)
        if target_user_ids:
            msg_query = msg_query.filter(Message.user_id.in_(target_user_ids))
        messages = msg_query.order_by(Message.chat_instance_id, Message.created_at).limit(5000).all()

        chat_groups: dict[str, dict] = {}
        for m in messages:
            grp = chat_groups.setdefault(
                m.chat_instance_id,
                {"message_ids": [], "user_ids": set(), "chat_id": m.chat_instance_id},
            )
            if m.id:
                grp["message_ids"].append(m.id)
            if m.user_id:
                grp["user_ids"].add(m.user_id)

        # Fetch user records for all involved users to map emails
        all_user_ids = set().union(*[g["user_ids"] for g in chat_groups.values()]) if chat_groups else set()
        if all_user_ids and not user_map:
            user_rows = db.query(User).filter(User.id.in_(list(all_user_ids))).all()
            user_map = {u.id: u for u in user_rows}
        elif all_user_ids:
            missing = [uid for uid in all_user_ids if uid not in user_map]
            if missing:
                user_rows = db.query(User).filter(User.id.in_(missing)).all()
                for u in user_rows:
                    user_map[u.id] = u

        notifications_by_hash = {}
        if include_notifications:
            notifications = (
                db.query(Notification)
                .filter(Notification.created_at >= window_start)
                .all()
            )
            for n in notifications:
                if n.signal_hash:
                    notifications_by_hash.setdefault(n.signal_hash, []).append(n)

        existing_signals = {
            row.computed_hash: row
            for row in db.query(CollaborationSignal).filter(CollaborationSignal.created_at >= window_start).all()
        }

        computed = []
        mismatches = []
        saved_count = 0

        for chat_id, info in chat_groups.items():
            user_ids_list = sorted(list(info["user_ids"]))
            message_ids_list = sorted(info["message_ids"])
            if not message_ids_list or not user_ids_list:
                continue
            involved_emails = [user_map[uid].email for uid in user_ids_list if uid in user_map]
            hash_basis = f"chat_activity|{chat_id}|{','.join(user_ids_list)}|{','.join(message_ids_list)}|{window_start.date().isoformat()}"
            computed_hash = hashlib.sha1(hash_basis.encode("utf-8")).hexdigest()
            score = len(message_ids_list)

            matched_notification_id = None
            notifications_for_hash = notifications_by_hash.get(computed_hash, [])
            if notifications_for_hash:
                matched_notification_id = notifications_for_hash[0].id

            existing = existing_signals.get(computed_hash)
            sent_flag = matched_notification_id is not None or (existing.sent if existing else False)
            expected_send = True  # any chat activity should produce a signal

            if expected_send and not sent_flag:
                mismatches.append(
                    {
                        "computed_hash": computed_hash,
                        "chat_id": chat_id,
                        "user_ids": user_ids_list,
                        "user_emails": involved_emails,
                        "messages": len(message_ids_list),
                        "reason": "missing_notification",
                    }
                )

            signal_payload = {
                "id": str(uuid.uuid4()),
                "signal_type": "chat_activity",
                "user_ids": user_ids_list,
                "chat_id": chat_id,
                "message_ids": message_ids_list,
                "computed_hash": computed_hash,
                "notification_id": matched_notification_id,
                "sent": sent_flag,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "score": score,
                "details": {
                    "user_emails": involved_emails,
                    "messages_count": len(message_ids_list),
                    "notifications_found": len(notifications_for_hash),
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                },
            }
            computed.append(signal_payload)

        if persist and computed:
            existing_hashes = set(existing_signals.keys())
            for c in computed:
                if c["computed_hash"] in existing_hashes:
                    continue
                db.add(
                    CollaborationSignal(
                        id=c["id"],
                        signal_type=c["signal_type"],
                        user_ids=c["user_ids"],
                        chat_id=c["chat_id"],
                        message_ids=c["message_ids"],
                        computed_hash=c["computed_hash"],
                        notification_id=c["notification_id"],
                        sent=c["sent"],
                        window_start=datetime.fromisoformat(c["window_start"]),
                        window_end=datetime.fromisoformat(c["window_end"]),
                        score=c["score"],
                        details=c["details"],
                    )
                )
                saved_count += 1
            db.add(
                CollaborationAuditRun(
                    id=request_id,
                    params={"users": users, "days": days, "persist": persist},
                    stats={
                        "signals_computed": len(computed),
                        "signals_saved": saved_count,
                        "notifications_matched": sum(len(v) for v in notifications_by_hash.values()),
                        "mismatches": len(mismatches),
                    },
                    sample_mismatches=mismatches[:20],
                )
            )
            db.commit()

        sample_mismatches = mismatches[:20]

        return admin_ok(
            request=request,
            data={
                "run_id": request_id,
                "signals_computed": len(computed),
                "signals_saved": saved_count,
                "notifications_matched": sum(len(v) for v in notifications_by_hash.values()),
                "mismatches_count": len(mismatches),
                "sample_mismatches": sample_mismatches,
                "persist": persist,
            },
            debug={
                "input": {"users": users or "ALL", "days": days, "persist": persist},
                "output": {
                    "signals_computed": len(computed),
                    "signals_saved": saved_count,
                    "mismatches_count": len(mismatches),
                },
                "db": {"tables_queried": ["messages", "notifications", "users", "collaboration_signals"]},
            },
        )
    except Exception as exc:
        logger.exception("Failed to run collaboration audit", extra={"request_id": request_id})
        return admin_fail(
            request=request,
            code="COLLAB_AUDIT_ERROR",
            message="Failed to run collaboration audit",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )


@router.get("/collaboration-graph")
async def collaboration_graph(
    request: Request,
    users: Optional[List[str]] = Query(default=None, description="Filter to specific user emails"),
    days: int = Query(7, ge=1, le=90),
    depth: int = Query(50, ge=1, le=500),
    include_messages: bool = Query(True),
    include_summaries: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    request_id = str(uuid.uuid4())
    try:
        window_start = datetime.utcnow() - timedelta(days=days)
        user_map = {}
        if users:
            user_rows = db.query(User).filter(User.email.in_(users)).all()
            user_map = {u.id: u for u in user_rows}
            target_user_ids = set(user_map.keys())
        else:
            target_user_ids = None

        msg_query = db.query(Message).filter(Message.created_at >= window_start)
        if target_user_ids:
            msg_query = msg_query.filter(Message.user_id.in_(target_user_ids))
        messages = msg_query.order_by(Message.created_at.desc()).limit(depth).all()

        chat_threads: dict[str, dict] = {}
        for m in messages:
            thread = chat_threads.setdefault(
                m.chat_instance_id,
                {"messages": [], "user_ids": set(), "chat_id": m.chat_instance_id},
            )
            thread["messages"].append(m)
            if m.user_id:
                thread["user_ids"].add(m.user_id)

        # hydrate missing users
        all_user_ids = set().union(*[t["user_ids"] for t in chat_threads.values()]) if chat_threads else set()
        missing_ids = [uid for uid in all_user_ids if uid not in user_map]
        if missing_ids:
            user_rows = db.query(User).filter(User.id.in_(missing_ids)).all()
            for u in user_rows:
                user_map[u.id] = u

        nodes = []
        edges = []
        threads_out = []
        signals_out = []

        for chat_id, info in chat_threads.items():
            participants_emails = [user_map[uid].email for uid in info["user_ids"] if uid in user_map]
            msgs_sorted = sorted(info["messages"], key=lambda m: m.created_at)
            if include_messages:
                msg_payloads = []
                for m in msgs_sorted:
                    msg_payloads.append(
                        {
                            "id": m.id,
                            "ts": m.created_at.isoformat() if m.created_at else None,
                            "role": m.role or "unknown",
                            "from_email": user_map.get(m.user_id).email if m.user_id in user_map else None,
                            "text_preview": (m.content or "")[:200] if m.content else None,
                        }
                    )
            else:
                msg_payloads = []

            threads_out.append(
                {
                    "chat_id": chat_id,
                    "participants": participants_emails,
                    "first_activity": msgs_sorted[0].created_at.isoformat() if msgs_sorted and msgs_sorted[0].created_at else None,
                    "last_activity": msgs_sorted[-1].created_at.isoformat() if msgs_sorted and msgs_sorted[-1].created_at else None,
                    "message_count": len(msgs_sorted),
                    "messages": msg_payloads if include_messages else [],
                    "summaries": [],  # placeholder; no summaries implemented
                }
            )

            for email in participants_emails:
                nodes.append({"id": email, "type": "user", "label": email, "meta": {}})
            for i, email1 in enumerate(participants_emails):
                for email2 in participants_emails[i + 1 :]:
                    edge_id = f"{chat_id}:{email1}:{email2}"
                    edges.append(
                        {
                            "id": edge_id,
                            "source": email1,
                            "target": email2,
                            "type": "chat",
                            "weight": len(msgs_sorted),
                            "meta": {"chat_id": chat_id},
                        }
                    )

        # Signals from stored collaboration_signals in window
        signals_rows = (
            db.query(CollaborationSignal)
            .filter(CollaborationSignal.created_at >= window_start)
            .order_by(CollaborationSignal.created_at.desc())
            .limit(200)
            .all()
        )
        for s in signals_rows:
            signals_out.append(
                {
                    "computed_hash": s.computed_hash,
                    "type": s.signal_type,
                    "chat_id": s.chat_id,
                    "user_ids": s.user_ids or [],
                    "message_ids": s.message_ids or [],
                    "window_start": s.window_start.isoformat() if s.window_start else None,
                    "window_end": s.window_end.isoformat() if s.window_end else None,
                    "score": s.score,
                    "expected_send": True,
                    "actually_sent": bool(s.sent),
                    "notification_id": s.notification_id,
                }
            )

        data = {
            "users": [{"id": uid, "email": user_map[uid].email} for uid in user_map],
            "date_range": {"start": window_start.isoformat(), "end": datetime.utcnow().isoformat()},
            "nodes": nodes,
            "edges": edges,
            "threads": threads_out,
            "signals": signals_out,
            "overview": {
                "total_threads": len(threads_out),
                "total_messages": len(messages),
                "total_signals": len(signals_out),
            },
        }

        return admin_ok(
            request=request,
            data=_safe_json(data),
            debug={
                "input": {
                    "users": users or "ALL",
                    "days": days,
                    "depth": depth,
                    "include_messages": include_messages,
                },
                "output": {"threads": len(threads_out), "signals": len(signals_out)},
            },
        )
    except Exception as exc:
        logger.exception("Failed to build collaboration graph", extra={"request_id": request_id})
        return admin_fail(
            request=request,
            code="COLLAB_GRAPH_ERROR",
            message="Failed to build collaboration graph",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )
