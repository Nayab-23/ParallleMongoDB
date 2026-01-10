from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import SessionLocal

router = APIRouter(prefix="/outbound", tags=["outbound"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_user(request: Request, db: Session):
    from main import require_user as _require_user
    return _require_user(request, db)


@router.get("/summary")
def outbound_summary(
    request: Request,
    db: Session = Depends(get_db),
):
    require_user(request, db)
    # Placeholder structure per spec
    return {
        "at_risk_clients": [],
        "client_sentiment": {},
        "opportunities": [],
        "external_triggers": [],
    }
