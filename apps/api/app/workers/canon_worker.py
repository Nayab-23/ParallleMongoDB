import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import SessionLocal
from models import User as UserORM, UserCanonicalPlan
from app.services.gmail import fetch_unread_emails
from app.services.calendar import fetch_upcoming_events
from app.services.canon import generate_recommendations

# Use root logger to ensure logs propagate to main FastAPI logger
logger = logging.getLogger("canon_worker")
logger.setLevel(logging.INFO)
logger.propagate = True  # Let logs flow to root logger

# Add dedicated handler with clear prefix
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("🔄 [Canon Worker] [%(asctime)s] %(message)s"))
logger.addHandler(handler)

# Central place to configure how often the worker checks for stale canons
CANON_WORKER_CHECK_INTERVAL_MINUTES = 1
# Only show detailed per-user logs for this email (reduce noise)
CANON_DEBUG_EMAIL = "severin.spagnola@sjsu.edu"


async def refresh_stale_canons():
    """
    Background worker to auto-refresh canons based on each user's preference.
    Runs every 15 minutes (or 1 min in DEBUG mode), but only refreshes users whose interval has elapsed.
    """
    if os.getenv("DISABLE_CANON_AUTOFILL", "").lower() in {"1", "true", "yes", "on"}:
        logger.info("⚠️  Canon autofill disabled (DISABLE_CANON_AUTOFILL). Skipping refresh cycle.")
        return
    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        all_canons = db.query(UserCanonicalPlan).all()

        logger.info(f"🔄 Cycle start: {len(all_canons)} canons")

        refreshed_count = 0
        skipped_disabled = 0
        skipped_too_soon = 0
        skipped_oauth = 0
        skipped_errors = 0

        # Track which users were refreshed vs skipped
        refreshed_users = []
        too_soon_users = []

        for canon in all_canons:
            try:
                user = db.query(UserORM).get(canon.user_id)
                if not user:
                    logger.warning(f"Canon {canon.id} has no user - skipping")
                    continue

                prefs = getattr(user, "preferences", None) or {}
                interval_minutes = prefs.get("canon_refresh_interval_minutes", 60)

                debug_for_user = getattr(user, "email", None) == CANON_DEBUG_EMAIL
                # Only emit per-user logs for the debug account to reduce noise
                if debug_for_user:
                    logger.info(
                        f"User {user.email} ({user.id[:8]}...): interval={interval_minutes}min"
                    )

                # Skip if user disabled auto-refresh
                if interval_minutes == 0:
                    skipped_disabled += 1
                    if debug_for_user:
                        logger.info("  ⏭️  Skipped (auto-refresh disabled)")
                    continue

                # Skip if not enough time has passed
                if canon.last_ai_sync:
                    # Handle timezone-naive last_ai_sync
                    last_sync = canon.last_ai_sync
                    if last_sync.tzinfo is None:
                        last_sync = last_sync.replace(tzinfo=timezone.utc)

                    time_since_sync = now - last_sync
                    minutes_since_sync = time_since_sync.total_seconds() / 60
                    if minutes_since_sync < interval_minutes:
                        skipped_too_soon += 1
                        user_email = getattr(user, "email", user.id[:8])
                        too_soon_users.append(f"{user_email} ({minutes_since_sync:.1f}m/{interval_minutes}m)")
                        if debug_for_user:
                            logger.info(
                                f"  ⏭️  Skipped (only {minutes_since_sync:.1f}m ago, "
                                f"need {interval_minutes}m)"
                            )
                        continue
                    if debug_for_user:
                        logger.info(
                            f"User {user.email}: {minutes_since_sync:.1f}m since sync, "
                            f"interval={interval_minutes}m → REFRESHING"
                        )
                else:
                    if debug_for_user:
                        logger.info("User debug account: Never synced → REFRESHING")

                # Fetch fresh data (may fail if OAuth expired)
                try:
                    emails = fetch_unread_emails(user, db)
                    events = fetch_upcoming_events(user, db)
                    if debug_for_user:
                        logger.info(f"  📧 Fetched {len(emails)} emails, 📅 {len(events)} events")
                except Exception as oauth_err:
                    error_str = str(oauth_err)
                    if "oauth_not_connected" in error_str:
                        if debug_for_user:
                            logger.info("  ℹ️  Gmail/Calendar not connected (expected)")
                    elif "oauth_expired" in error_str or "invalid_grant" in error_str:
                        if debug_for_user:
                            logger.warning("  ⚠️  OAuth token expired → reconnect in Settings")
                    else:
                        if debug_for_user:
                            logger.error(f"  ❌ Unexpected OAuth error: {oauth_err}")
                    db.rollback()
                    skipped_oauth += 1
                    continue

                # Update context store with fresh data to prevent re-processing
                try:
                    from models import UserContextStore
                    from app.services.canon import merge_and_dedupe

                    context_store = db.query(UserContextStore).filter(
                        UserContextStore.user_id == user.id
                    ).first()

                    if not context_store:
                        import uuid
                        context_store = UserContextStore(
                            id=str(uuid.uuid4()),
                            user_id=user.id,
                            emails_recent=[],
                            calendar_recent=[],
                        )
                        db.add(context_store)

                    # Merge new data with existing cache
                    existing_emails = context_store.emails_recent or []
                    merged_emails = merge_and_dedupe(existing_emails, emails)
                    context_store.emails_recent = merged_emails
                    context_store.last_email_sync = now

                    existing_events = context_store.calendar_recent or []
                    merged_events = merge_and_dedupe(existing_events, events)
                    context_store.calendar_recent = merged_events
                    context_store.last_calendar_sync = now

                    db.commit()

                    if debug_for_user:
                        logger.info(f"  📦 Updated context store: {len(merged_emails)} emails, {len(merged_events)} events cached")
                except Exception as ctx_err:
                    logger.warning(f"  ⚠️  Context store update failed: {ctx_err}")
                    # Continue anyway - generation can work with fresh data

                # Generate recommendations
                try:
                    new_recs = generate_recommendations(
                        user=user,
                        emails=emails,
                        events=events,
                        canonical_plan=canon,
                        db=db,
                        is_manual_refresh=False,
                    )

                    # Update sync timestamp
                    canon.last_ai_sync = now
                    db.commit()

                    refreshed_count += 1
                    user_email = getattr(user, "email", user.id[:8])
                    added_count = new_recs.get("added", 0) if isinstance(new_recs, dict) else 0
                    refreshed_users.append(f"{user_email} (+{added_count} items)")
                    if debug_for_user:
                        logger.info(f"  ✅ Refreshed! Added {added_count} items to timeline")

                except Exception as gen_err:
                    if debug_for_user:
                        logger.error(f"  ❌ Recommendation generation failed: {gen_err}", exc_info=True)
                    skipped_errors += 1
                    db.rollback()
                    continue

            except Exception as e:
                logger.error(f"❌ Failed for canon {canon.id}: {e}", exc_info=True)
                skipped_errors += 1
                db.rollback()
                continue

        summary_parts = [f"✅ {refreshed_count} refreshed"]
        if skipped_disabled > 0:
            summary_parts.append(f"⏸️  {skipped_disabled} disabled")
        if skipped_too_soon > 0:
            summary_parts.append(f"⏭️  {skipped_too_soon} too soon")
        if skipped_oauth > 0:
            summary_parts.append(f"ℹ️  {skipped_oauth} need Gmail/Calendar connection")
        if skipped_errors > 0:
            summary_parts.append(f"❌ {skipped_errors} errors")

        logger.info(f"════════════════════════════════════════════════════════════════")
        logger.info(f"Cycle complete: {' | '.join(summary_parts)}")

        # Print detailed lists
        if refreshed_users:
            logger.info(f"✅ Refreshed users:")
            for user_info in refreshed_users:
                logger.info(f"   • {user_info}")

        if too_soon_users:
            logger.info(f"⏭️  Skipped (too soon):")
            for user_info in too_soon_users:
                logger.info(f"   • {user_info}")

        logger.info(f"════════════════════════════════════════════════════════════════")

    except Exception as e:
        logger.error(f"❌❌❌ WORKER CRASHED: {e}", exc_info=True)
    finally:
        db.close()


from apscheduler.schedulers.asyncio import AsyncIOScheduler


scheduler = AsyncIOScheduler()

# Flag to prevent duplicate workers in multi-process environments
_worker_started = False


def start_canon_worker():
    """
    Start the background canon refresh worker.
    IMPORTANT: Only starts in the FIRST process (prevents duplicates in multi-worker setups).
    """
    global _worker_started

    # Prevent duplicate workers in multi-process environments
    # Only the first process to call this will start the scheduler
    if _worker_started:
        logger.warning("⚠️  Worker already started in this process, skipping duplicate")
        return

    # Check if scheduler is already running (in case of app reload)
    if scheduler.running:
        logger.warning("⚠️  Scheduler already running, skipping duplicate")
        return

    scheduler.add_job(
        refresh_stale_canons,
        "interval",
        minutes=CANON_WORKER_CHECK_INTERVAL_MINUTES,
        id="canon_refresh_worker",
        replace_existing=True,
    )
    scheduler.start()
    _worker_started = True

    next_runs = scheduler.get_jobs()
    next_run_str = ", ".join([str(j.next_run_time) for j in next_runs if j.next_run_time])

    logger.info("════════════════════════════════════════════════════════════════")
    logger.info(f"🚀 STARTED (interval: {CANON_WORKER_CHECK_INTERVAL_MINUTES} minute(s))")
    logger.info(f"📅 Next run: {next_run_str}")
    logger.info(f"⚙️  Process ID: {os.getpid()}")
    logger.info("════════════════════════════════════════════════════════════════")
