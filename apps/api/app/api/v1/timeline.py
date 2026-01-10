import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.api.v1.deps import get_current_user, get_db
from models import User, UserCanonicalPlan

logger = logging.getLogger(__name__)
router = APIRouter()


class TimelineResponse(BaseModel):
    daily_goals: list
    weekly_focus: list
    monthly_objectives: list


@router.get("/users/me/timeline", response_model=TimelineResponse)
async def get_my_timeline(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        logger.info(
            "[TIMELINE] Request from user_id=%s email=%s",
            getattr(current_user, "id", None),
            getattr(current_user, "email", None),
        )

        plan = (
            db.query(UserCanonicalPlan)
            .filter(UserCanonicalPlan.user_id == current_user.id)
            .first()
        )

        if not plan or not plan.approved_timeline:
            logger.info(
                "[TIMELINE] No plan found for user %s, returning empty",
                getattr(current_user, "id", None),
            )
            return TimelineResponse(
                daily_goals=[],
                weekly_focus=[],
                monthly_objectives=[],
            )

        timeline_data = plan.approved_timeline or {}

        daily_goals = timeline_data.get("1d", {})
        weekly_focus = timeline_data.get("7d", {})
        monthly_objectives = timeline_data.get("28d", {})

        if isinstance(daily_goals, dict) and "normal" in daily_goals:
            daily_goals = daily_goals["normal"]
        elif not isinstance(daily_goals, list):
            daily_goals = []

        if isinstance(weekly_focus, dict) and "normal" in weekly_focus:
            weekly_focus = weekly_focus["normal"]
        elif not isinstance(weekly_focus, list):
            weekly_focus = []

        if isinstance(monthly_objectives, dict) and "normal" in monthly_objectives:
            monthly_objectives = monthly_objectives["normal"]
        elif not isinstance(monthly_objectives, list):
            monthly_objectives = []

        logger.info(
            "[TIMELINE] Found plan for user %s, returning %d daily, %d weekly, %d monthly items",
            getattr(current_user, "id", None),
            len(daily_goals),
            len(weekly_focus),
            len(monthly_objectives),
        )
        logger.debug("[TIMELINE] Timeline data: %s", plan.approved_timeline)

        return TimelineResponse(
            daily_goals=daily_goals,
            weekly_focus=weekly_focus,
            monthly_objectives=monthly_objectives,
        )
    except Exception as e:
        logger.error("[TIMELINE] Error fetching timeline: %s", e, exc_info=True)
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch timeline: {str(e)}",
        )
