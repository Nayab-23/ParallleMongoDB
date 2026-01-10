import hashlib
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models import UserCanonicalPlan
from sqlalchemy.orm.attributes import flag_modified


def generate_signature(timeframe: str, priority: str, title: str) -> str:
    """Generate MD5 signature for a timeline item."""
    canonical_string = f"{timeframe}|{priority}|{title.strip().lower()}"
    return hashlib.md5(canonical_string.encode()).hexdigest()


def backfill_signatures():
    db = SessionLocal()

    try:
        plans = db.query(UserCanonicalPlan).all()

        for plan in plans:
            if not plan.approved_timeline:
                continue

            timeline = plan.approved_timeline
            updated = False

            for timeframe in ["1d", "7d", "28d"]:
                if timeframe not in timeline:
                    continue

                for priority in ["critical", "high", "medium", "low", "normal", "high_priority"]:
                    if priority not in timeline[timeframe]:
                        continue

                    items = timeline[timeframe][priority]
                    for item in items:
                        if item.get("signature"):
                            continue
                        title = item.get("title", "")
                        signature = generate_signature(timeframe, priority, title)
                        item["signature"] = signature
                        updated = True
                        print(f"✅ Added signature to: {title[:50]} -> {signature}")

            if updated:
                flag_modified(plan, "approved_timeline")
                db.commit()
                print(f"✅ Updated canonical plan for user {plan.user_id}")

        print("\n🎉 Backfill complete!")

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    backfill_signatures()
