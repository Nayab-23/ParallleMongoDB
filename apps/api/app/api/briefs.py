"""
Daily Brief generation service with real Gmail/Calendar integration
"""
import uuid
from datetime import datetime, timezone
from typing import List

from sqlalchemy.orm import Session
from fastapi import APIRouter

from models import ExternalAccount, User as UserORM

router = APIRouter(prefix="/brief", tags=["briefs"])

class MissingIntegrationsError(Exception):
    """Raised when required integrations are not connected"""
    def __init__(self, missing: List[str]):
        self.missing = missing
        super().__init__(f"Missing integrations: {missing}")


def _check_integrations(user: UserORM, db: Session) -> List[str]:
    """Check which required integrations are missing"""
    required = ["google_gmail", "google_calendar"]
    connected = db.query(ExternalAccount.provider).filter(
        ExternalAccount.user_id == user.id
    ).all()
    connected_providers = {row[0] for row in connected}
    
    missing = [p for p in required if p not in connected_providers]
    return missing


def generate_daily_brief(user: UserORM, db: Session) -> dict:
    """
    Generate daily brief with real data from Gmail and Calendar
    
    Returns structured JSON with:
    - personal: { emails, calendar, tasks, mentions, priorities }
    - org: { fires, bottlenecks, sentiment, active_rooms }
    - outbound: { at_risk, opportunities, sentiment }
    """
    
    # Check integrations first
    missing = _check_integrations(user, db)
    if missing:
        raise MissingIntegrationsError(missing)
    
    # Import here to avoid circular dependencies and make them optional
    from app.services.gmail import fetch_unread_emails
    from app.services.calendar import fetch_upcoming_events
    
    # Fetch real data
    try:
        emails = fetch_unread_emails(user, db)
    except Exception as e:
        print(f"Error fetching emails: {e}")
        emails = []
    
    try:
        events = fetch_upcoming_events(user, db)
    except Exception as e:
        print(f"Error fetching calendar: {e}")
        events = []
    
    # Build personal brief
    personal = {
        "emails": emails,
        "calendar": events,
        "tasks": _extract_tasks_from_emails(emails),  # Smart extraction
        "mentions": [],  # TODO: Extract from team chat
        "priorities": _generate_priorities(emails, events)
    }
    
    # Build org brief (stub for now - will be enhanced)
    org = {
        "fires": [],  # TODO: Extract from rooms
        "bottlenecks": [],
        "sentiment": {"overall": 0.5},
        "active_rooms": []
    }
    
    # Build outbound brief (stub for now)
    outbound = {
        "at_risk": [],
        "opportunities": [],
        "sentiment": {}
    }
    
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "personal": personal,
        "org": org,
        "outbound": outbound,
    }


def _extract_tasks_from_emails(emails: List[dict]) -> List[dict]:
    """
    Extract actionable tasks from email subjects/snippets
    Look for keywords like: TODO, action item, please review, etc.
    """
    tasks = []
    task_keywords = ['todo', 'action', 'review', 'please', 'need', 'asap', 'urgent']
    
    for email in emails[:10]:  # Check first 10 emails
        subject = email.get('subject', '').lower()
        snippet = email.get('snippet', '').lower()
        
        # Check if email looks like a task
        if any(keyword in subject or keyword in snippet for keyword in task_keywords):
            tasks.append({
                "title": email.get('subject', 'No subject'),
                "from": email.get('from', 'Unknown'),
                "snippet": email.get('snippet', '')[:100],
                "email_id": email.get('id')
            })
    
    return tasks


def _generate_priorities(emails: List[dict], events: List[dict]) -> List[dict]:
    """
    Generate prioritized list of what to focus on today
    Combines urgent emails + upcoming meetings
    """
    priorities = []
    
    # Add urgent emails as high priority
    urgent_keywords = ['urgent', 'asap', 'important', 'critical', 'deadline']
    for email in emails[:5]:
        subject = email.get('subject', '').lower()
        if any(keyword in subject for keyword in urgent_keywords):
            priorities.append({
                "type": "email",
                "priority": "high",
                "title": email.get('subject', 'No subject'),
                "from": email.get('from', 'Unknown')
            })
    
    # Add today's meetings as priorities
    today = datetime.now(timezone.utc).date().isoformat()
    for event in events:
        event_start = event.get('start', '')
        if today in event_start:
            priorities.append({
                "type": "meeting",
                "priority": "medium",
                "title": event.get('summary', 'No title'),
                "time": event_start
            })
    
    return priorities[:10]  # Top 10 priorities