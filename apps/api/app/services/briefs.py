"""
Daily Brief API endpoints
"""
from datetime import datetime, timezone
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import SessionLocal
from models import DailyBrief as DailyBriefORM, User as UserORM
from ..api.briefs import generate_daily_brief, MissingIntegrationsError

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def require_user(request: Request, db: Session) -> UserORM:
    """Lazy import to avoid circular imports"""
    from main import require_user as main_require_user
    return main_require_user(request, db)


@router.get("/today")
def get_daily_brief(
    request: Request,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """
    Get daily brief for the current user
    
    - Cached per user per day
    - Use ?force=true to regenerate
    - Returns structured personal/org/outbound data
    - Returns error if integrations missing
    """
    current_user = require_user(request, db)
    today = datetime.now(timezone.utc).date()

    # Check cache
    brief = (
        db.query(DailyBriefORM)
        .filter(
            DailyBriefORM.user_id == current_user.id,
            DailyBriefORM.date == today
        )
        .first()
    )

    # Return cached if exists and not forcing refresh
    if brief and not force:
        return {
            "date": brief.date.isoformat(),
            "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
            **brief.summary_json,
        }

    # Generate new brief
    try:
        summary = generate_daily_brief(current_user, db)
    except MissingIntegrationsError as mie:
        return {
            "error": "missing_integrations",
            "missing": mie.missing
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Save to database
    if brief:
        brief.summary_json = summary
        brief.generated_at = datetime.now(timezone.utc)
    else:
        brief = DailyBriefORM(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            org_id=getattr(current_user, "org_id", None),
            date=today,
            summary_json=summary,
            generated_at=datetime.now(timezone.utc),
        )
        db.add(brief)
    
    db.commit()

    # Return structured response
    return {
        "date": summary.get("date"),
        "generated_at": summary.get("generated_at"),
        "personal": summary.get("personal", {}),
        "org": summary.get("org", {}),
        "outbound": summary.get("outbound", {}),
    }