"""
Google Calendar service for fetching events (httpx-based)
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import httpx
import os
import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException

from models import ExternalAccount as ExternalAccountORM, User as UserORM

logger = logging.getLogger(__name__)

# Only log OAuth errors for this email (reduces noise in production logs)
CANON_DEBUG_EMAIL = os.getenv("CANON_DEBUG_EMAIL", "").lower()

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _should_log_oauth_error(user_email: str) -> bool:
    """Only log OAuth errors for debug user to reduce log noise."""
    if not CANON_DEBUG_EMAIL:
        return True  # Log everything if no debug email set
    return user_email.lower() == CANON_DEBUG_EMAIL


def _normalize_expires_at(value: Optional[datetime]) -> Optional[datetime]:
    """Make expires_at timezone-aware for safe comparisons."""
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def refresh_access_token(refresh_token: str, user_email: str = "") -> Optional[Dict]:
    """Refresh an expired OAuth access token. Returns payload or None."""
    data = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    try:
        resp = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=10)
        if resp.status_code != 200:
            # Only log for debug user
            if _should_log_oauth_error(user_email):
                logger.error(f"[OAuth] Refresh token request failed: {resp.status_code} {resp.text}")
            else:
                logger.debug(f"[OAuth] Refresh failed for {user_email}: {resp.status_code}")
            return None
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            # Only log for debug user
            if _should_log_oauth_error(user_email):
                logger.error(f"[OAuth] Refresh response missing access_token: {payload}")
            else:
                logger.debug(f"[OAuth] Refresh response missing token for {user_email}")
            return None
        return payload
    except Exception as e:
        # Only log for debug user
        if _should_log_oauth_error(user_email):
            logger.error(f"[OAuth] Exception during refresh: {e}", exc_info=True)
        else:
            logger.debug(f"[OAuth] Refresh exception for {user_email}: {e}")
        return None


def _get_valid_token(user: UserORM, db: Session) -> str:
    """
    Get valid access token, refreshing if expired. Raises HTTPException when not recoverable.
    """
    user_email = getattr(user, "email", "")

    account = (
        db.query(ExternalAccountORM)
        .filter(ExternalAccountORM.user_id == user.id, ExternalAccountORM.provider == "google_calendar")
        .first()
    )
    if not account:
        # Only log for debug user
        if _should_log_oauth_error(user_email):
            logger.error(f"[OAuth] User {user.id} has no google_calendar account")
        else:
            logger.debug(f"[OAuth] User {user_email} has no google_calendar account")
        raise HTTPException(
            status_code=401,
            detail={
                "error": "oauth_not_connected",
                "provider": "google_calendar",
                "message": "Please connect Calendar in Settings",
            },
        )

    now = datetime.now(timezone.utc)
    expires_at_aware = _normalize_expires_at(account.expires_at)
    if expires_at_aware and expires_at_aware < (now + timedelta(minutes=5)):
        # Only log for debug user
        if _should_log_oauth_error(user_email):
            logger.info(f"[OAuth] Token expired for user {user.id}, attempting refresh...")

        if not account.refresh_token:
            # Only log for debug user
            if _should_log_oauth_error(user_email):
                logger.error(f"[OAuth] No refresh token for user {user.id}")
            else:
                logger.debug(f"[OAuth] No refresh token for {user_email}")
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "oauth_expired",
                    "provider": "google_calendar",
                    "message": "Your Calendar connection expired. Please reconnect in Settings.",
                },
            )
        token_payload = refresh_access_token(account.refresh_token, user_email)
        if not token_payload or not token_payload.get("access_token"):
            # Only log for debug user
            if _should_log_oauth_error(user_email):
                logger.error(f"[OAuth] Failed to refresh token for user {user.id}")
            else:
                logger.debug(f"[OAuth] Failed to refresh token for {user_email}")
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "oauth_refresh_failed",
                    "provider": "google_calendar",
                    "message": "Failed to refresh Calendar token. Please reconnect in Settings.",
                },
            )
        account.access_token = token_payload["access_token"]
        account.expires_at = now + timedelta(seconds=token_payload.get("expires_in", 3600))
        db.commit()
        # Only log for debug user
        if _should_log_oauth_error(user_email):
            logger.info(f"[OAuth] ✅ Successfully refreshed token for user {user.id}")

    if not account.access_token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "oauth_missing",
                "provider": "google_calendar",
                "message": "No Calendar access token found. Please reconnect in Settings.",
            },
        )

    return account.access_token

def fetch_events_raw(access_token: str, days_ahead: int = 30) -> List[Dict]:
    """
    Fetch calendar events using raw access token - looks FORWARD in time.
    
    Args:
        access_token: Google OAuth token
        days_ahead: How many days into the future to fetch (default 30)
    
    Returns:
        List of event dicts with id, summary, start, end, location, link, etc.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # Time range: NOW to +days_ahead (FORWARD LOOKING)
    now = datetime.now(timezone.utc)
    future = now + timedelta(days=days_ahead)
    
    params = {
        "timeMin": now.isoformat(),  # Start from NOW (not midnight)
        "timeMax": future.isoformat(),  # Look AHEAD
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 50,  # Increased from 20
    }
    
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"[Calendar] API returned {resp.status_code}")
            return []
        
        data = resp.json()
        events = data.get("items", []) or []

        # LOG RAW API RESPONSE
        logger.warning("=" * 80)
        logger.warning(f"[CALENDAR RAW] Fetched {len(events)} events from Google Calendar API")
        logger.warning("=" * 80)

        # Count event titles
        from collections import Counter
        event_titles = Counter([ev.get('summary', 'NO TITLE') for ev in events])
        logger.warning("[CALENDAR RAW] Event title counts:")
        for title, count in sorted(event_titles.items()):
            logger.warning(f"  {count}x: {title}")
        logger.warning("=" * 80)

        normalized = []
        today = datetime.now(timezone.utc).date()
        
        for ev in events:
            start_at = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
            end_at = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
            
            # Determine if event is today
            is_today = False
            if start_at:
                try:
                    if 'T' in start_at:  # DateTime format
                        event_date = datetime.fromisoformat(start_at.replace('Z', '+00:00')).date()
                    else:  # Date only
                        event_date = datetime.fromisoformat(start_at).date()
                    is_today = event_date == today
                except:
                    pass
            
            event_id = ev.get("id")

            # CRITICAL: Must have source_id and source_type for deduplication
            if not event_id:
                logger.error(f"[Calendar] Event missing ID: {ev.get('summary')}")

            normalized.append({
                "id": event_id,
                "source_id": event_id,  # REQUIRED for deduplication
                "source_type": "calendar",  # REQUIRED for deduplication
                "summary": ev.get("summary", "No title"),
                "title": ev.get("summary", "No title"),  # Alias for compatibility
                "start": start_at,
                "start_time": start_at,  # Alias for compatibility
                "end": end_at,
                "end_time": end_at,  # Alias for compatibility
                "location": ev.get("location", ""),
                "is_all_day": bool(ev.get("start", {}).get("date")),
                "is_today": is_today,
                "attendees": len(ev.get("attendees", [])),
                "description": (ev.get("description") or "")[:100],  # First 100 chars
                "htmlLink": ev.get("htmlLink", ""),
                "link": ev.get("htmlLink") or f"https://calendar.google.com/calendar/event?eid={event_id}",
            })
            logger.debug(f"[Calendar] Event: {ev.get('summary')} ID: {event_id} Link: {normalized[-1]['link']}")
        
        logger.info(f"[Calendar] Fetched {len(normalized)} upcoming events (next {days_ahead} days)")
        return normalized
        
    except Exception as e:
        logger.error(f"[Calendar] Error fetching events: {e}")
        return []

def fetch_events(access_token: str) -> List[Dict]:
    """
    Fetch calendar events using raw access token
    (Kept for backward compatibility)
    """
    return fetch_events_raw(access_token)


def fetch_upcoming_events(user: UserORM, db: Session, days_ahead: int = 30) -> List[Dict]:
    """
    Fetch upcoming calendar events for a user (with automatic token refresh)
    
    LOOKS FORWARD: Gets events from now to +days_ahead days in the future.
    
    Returns list of dicts with:
    - id: Event ID
    - summary/title: Event title
    - start/start_time: Start datetime
    - end/end_time: End datetime  
    - location: Location
    - is_today: Whether event is today
    - attendees: Number of attendees
    - htmlLink: Link to event in Google Calendar
    """
    try:
        access_token = _get_valid_token(user, db)
        return fetch_events_raw(access_token, days_ahead=days_ahead)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Calendar] Unexpected error for user {user.id}: {e}", exc_info=True)
        return []
