import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from database import SessionLocal
from models import UserAction, Notification, User as UserORM
from app.services.conflict_detector import find_conflicts
from app.services.event_emitter import emit_event
from app.services.notifications import create_timeline_reminders

# Use root logger to ensure logs propagate to main FastAPI logger
logger = logging.getLogger("notification_worker")
logger.setLevel(logging.INFO)
logger.propagate = True

# Add dedicated handler with clear prefix
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("🔔 [Notification Worker] [%(asctime)s] %(message)s"))
logger.addHandler(handler)

# Central place to configure how often the worker checks for conflicts
NOTIFICATION_WORKER_CHECK_INTERVAL_MINUTES = int(
    os.getenv("NOTIFICATION_CHECK_INTERVAL_MINUTES", "15")
)
SEMANTIC_CONFLICT_THRESHOLD = float(os.getenv("SEMANTIC_CONFLICT_THRESHOLD", "0.75"))
# To reduce misses, always scan at least the last 60 minutes
MIN_SCAN_WINDOW_MINUTES = 60


async def detect_and_create_notifications():
    """
    Background worker to detect conflicts and create notifications.
    Runs every 15 minutes, scans recent activities for conflicts.
    """
    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        scan_minutes = max(NOTIFICATION_WORKER_CHECK_INTERVAL_MINUTES + 1, MIN_SCAN_WINDOW_MINUTES)
        since = now - timedelta(minutes=scan_minutes)

        # Get recent activities with summaries; embeddings may be null (still allows file conflicts)
        activities = db.query(UserAction).filter(
            UserAction.timestamp >= since,
            UserAction.activity_summary.isnot(None)
        ).all()

        logger.info(
            "🔍 Scanning recent activities for conflicts | window_minutes=%s total=%s",
            scan_minutes,
            len(activities),
        )

        notification_count = 0
        file_conflict_count = 0
        semantic_conflict_count = 0
        skipped_count = 0
        no_embedding_count = 0
        candidate_count = 0

        for activity in activities:
            try:
                candidate_count += 1
                if activity.activity_embedding is None:
                    no_embedding_count += 1

                # Get the user who created this activity
                activity_user = db.query(UserORM).filter_by(id=activity.user_id).first()
                if not activity_user:
                    logger.warning(f"Activity {activity.id} has no user - skipping")
                    skipped_count += 1
                    continue

                activity_user_name = activity_user.name if activity_user else "Unknown User"

                # Find conflicts for this activity
                conflicts = find_conflicts(
                    db=db,
                    activity=activity,
                    file_conflict_window_hours=24,
                    semantic_similarity_threshold=SEMANTIC_CONFLICT_THRESHOLD,
                    semantic_window_days=7
                )

                # Create notifications for each conflict
                for conflict in conflicts:
                    try:
                        affected_user_id = conflict['affected_user_id']
                        conflict_type = conflict['conflict_type']
                        affected_user_name = conflict['affected_user_name']

                        # Determine notification details based on conflict type
                        if conflict_type == 'file':
                            file_conflict_count += 1
                            severity = 'urgent'
                            title = f"File Conflict with {activity_user_name}"
                            file_name = conflict['file_name']
                            message = (
                                f"{activity_user_name} is also working on {file_name}. "
                                f"You may want to coordinate to avoid merge conflicts."
                            )
                            source_type = 'conflict_file'

                        else:  # semantic conflict
                            semantic_conflict_count += 1
                            severity = 'normal'
                            title = f"Related Work: {activity_user_name}"
                            similarity_pct = int(conflict['similarity'] * 100)
                            message = (
                                f"{activity_user_name} is working on something similar ({similarity_pct}% match). "
                                f"Their activity: \"{activity.activity_summary[:100]}...\""
                            )
                            source_type = 'conflict_semantic'

                        # Check if we already created a similar notification recently (avoid spam)
                        recent_cutoff = now - timedelta(hours=1)
                        existing = db.query(Notification).filter(
                            Notification.user_id == affected_user_id,
                            Notification.source_type == source_type,
                            Notification.created_at >= recent_cutoff,
                            Notification.data['related_user_id'].astext == activity.user_id
                        ).first()

                        if existing:
                            # Skip duplicate notification
                            continue

                        # Create the notification
                        notification = Notification(
                            id=str(uuid.uuid4()),
                            user_id=affected_user_id,
                            type='conflict',
                            severity=severity,
                            title=title,
                            message=message,
                            source_type=source_type,
                            created_at=now,
                            is_read=False,
                            data={
                                'conflict_type': conflict_type,
                                'related_user_id': activity.user_id,
                                'related_user_name': activity_user_name,
                                'related_activity_id': activity.id,
                                'similarity': conflict.get('similarity', 1.0),
                                'files': conflict.get('files', []),
                                'activity_summary': activity.activity_summary
                            }
                        )

                        db.add(notification)
                        notification_count += 1

                        emit_event(
                            "notification_sent",
                            user_email=activity_user.email if activity_user else None,
                            target_email=affected_user_name,
                            metadata={
                                "conflict_type": conflict_type,
                                "activity_id": activity.id,
                                "target_user_id": affected_user_id,
                            },
                            request_id=str(uuid.uuid4()),
                            db=db,
                        )

                        logger.info(
                            f"📬 Created {severity} notification for {affected_user_name}: "
                            f"{conflict_type} conflict with {activity_user_name}"
                        )

                    except Exception as notif_err:
                        logger.error(f"Failed to create notification for conflict: {notif_err}", exc_info=True)
                        continue

                # Commit after processing each activity
                db.commit()

            except Exception as activity_err:
                logger.error(f"Failed to process activity {activity.id}: {activity_err}", exc_info=True)
                db.rollback()
                skipped_count += 1
                continue

        logger.info(f"════════════════════════════════════════════════════════════════")
        logger.info(f"✅ Scan complete: {notification_count} notifications created")
        logger.info(f"   📁 File conflicts: {file_conflict_count}")
        logger.info(f"   🧠 Semantic conflicts: {semantic_conflict_count}")
        logger.info(f"   📊 Candidates processed: {candidate_count}")
        logger.info(f"   ⚠️  Skipped (no embedding): {no_embedding_count}")
        if skipped_count > 0:
            logger.info(f"   ⏭️  Skipped: {skipped_count}")
        logger.info(f"════════════════════════════════════════════════════════════════")

        try:
            create_timeline_reminders(db)
        except Exception as exc:
            logger.error(f"Failed to create timeline reminders: {exc}", exc_info=True)

    except Exception as e:
        logger.error(f"❌❌❌ WORKER CRASHED: {e}", exc_info=True)
    finally:
        db.close()


from apscheduler.schedulers.asyncio import AsyncIOScheduler


scheduler = AsyncIOScheduler()

# Flag to prevent duplicate workers in multi-process environments
_worker_started = False


def start_notification_worker():
    """
    Start the background notification detection worker.
    IMPORTANT: Only starts in the FIRST process (prevents duplicates in multi-worker setups).
    """
    global _worker_started

    # Prevent duplicate workers in multi-process environments
    if _worker_started:
        logger.warning("⚠️  Worker already started in this process, skipping duplicate")
        return

    # Check if scheduler is already running (in case of app reload)
    if scheduler.running:
        logger.warning("⚠️  Scheduler already running, skipping duplicate")
        return

    scheduler.add_job(
        detect_and_create_notifications,
        "interval",
        minutes=NOTIFICATION_WORKER_CHECK_INTERVAL_MINUTES,
        id="notification_detection_worker",
        replace_existing=True,
    )
    scheduler.start()
    _worker_started = True

    next_runs = scheduler.get_jobs()
    next_run_str = ", ".join([str(j.next_run_time) for j in next_runs if j.next_run_time])

    logger.info("════════════════════════════════════════════════════════════════")
    logger.info(f"🚀 STARTED (interval: {NOTIFICATION_WORKER_CHECK_INTERVAL_MINUTES} minute(s))")
    logger.info(f"📅 Next run: {next_run_str}")
    logger.info(f"⚙️  Process ID: {os.getpid()}")
    logger.info("════════════════════════════════════════════════════════════════")
