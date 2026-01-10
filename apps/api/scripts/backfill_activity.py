"""
Backfill activity manager with historical messages.
Run once after deploying Activity Manager.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
import asyncio
import logging
import sys
import os

# Add parent directory to path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import User, Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill_activities(days: int = 7):
    """
    Process last N days of messages to populate activity manager.
    """
    from app.services.activity_manager import update_user_activity

    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Get all messages from last N days, ordered by time
        messages = db.query(Message).filter(
            Message.created_at >= since,
            Message.role == "user",  # Only user messages
            Message.user_id.isnot(None)
        ).order_by(Message.created_at).all()

        logger.info(f"Processing {len(messages)} messages from last {days} days")

        processed = 0
        skipped = 0
        errors = 0

        for i, msg in enumerate(messages):
            try:
                status_updated, activity_logged, _ = await update_user_activity(
                    user_id=msg.user_id,
                    content=msg.content,
                    room_id=msg.room_id,
                    action_type="chat_message",
                    tool="chat",
                    db=db
                )

                if status_updated or activity_logged:
                    processed += 1
                else:
                    skipped += 1

                if (i + 1) % 10 == 0:
                    logger.info(
                        f"Processed {i + 1}/{len(messages)} messages "
                        f"({processed} logged, {skipped} skipped, {errors} errors)"
                    )

            except Exception as e:
                logger.error(f"Error processing message {msg.id}: {e}")
                errors += 1
                continue

        logger.info(
            f"✅ Backfill complete: {processed} activities logged, "
            f"{skipped} skipped (similar), {errors} errors"
        )

    finally:
        db.close()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill Activity Manager with historical messages")
    parser.add_argument("--days", type=int, default=7, help="Number of days to backfill (default: 7)")
    args = parser.parse_args()

    logger.info(f"Starting backfill for last {args.days} days...")
    asyncio.run(backfill_activities(days=args.days))
