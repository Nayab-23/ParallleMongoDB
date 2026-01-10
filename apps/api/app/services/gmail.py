"""
Gmail service for fetching emails via Google API (httpx-based)
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import logging
import httpx
import os
from sqlalchemy.orm import Session
from fastapi import HTTPException

from models import (
    ExternalAccount as ExternalAccountORM,
    User as UserORM,
    UserContextStore,
)
import uuid


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
logger = logging.getLogger(__name__)

# Only log OAuth errors for this email (reduces noise in production logs)
CANON_DEBUG_EMAIL = os.getenv("CANON_DEBUG_EMAIL", "").lower()


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
    """Refresh an expired OAuth access token. Returns token payload or None."""
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
        .filter(ExternalAccountORM.user_id == user.id, ExternalAccountORM.provider == "google_gmail")
        .first()
    )
    if not account:
        # Only log for debug user
        if _should_log_oauth_error(user_email):
            logger.error(f"[OAuth] User {user.id} has no google_gmail account")
        else:
            logger.debug(f"[OAuth] User {user_email} has no google_gmail account")
        raise HTTPException(
            status_code=401,
            detail={
                "error": "oauth_not_connected",
                "provider": "google_gmail",
                "message": "Please connect Gmail in Settings",
            },
        )

    now = datetime.now(timezone.utc)
    expires_at_aware = _normalize_expires_at(account.expires_at)
    # Refresh if expiring within 5 minutes
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
                    "provider": "google_gmail",
                    "message": "Your Gmail connection expired. Please reconnect in Settings.",
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
                    "provider": "google_gmail",
                    "message": "Failed to refresh Gmail token. Please reconnect in Settings.",
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
                "provider": "google_gmail",
                "message": "No Gmail access token found. Please reconnect in Settings.",
            },
        )

    return account.access_token


def fetch_unread_emails_raw(access_token: str, max_total: int = 500, days_back: int = 30, batch_size: int = 100) -> List[Dict]:
    """
    Fetch unread emails using raw access token
    (Original implementation - kept for compatibility, now paginates up to max_total)
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    # Limit to recent window for context and to avoid huge crawls
    params = {"q": f"is:unread newer_than:{days_back}d", "maxResults": batch_size}
    base = "https://www.googleapis.com/gmail/v1/users/me/messages"
    
    try:
        results = []
        page_token = None

        while len(results) < max_total:
            page_params = dict(params)
            page_params["pageToken"] = page_token

            resp = httpx.get(base, headers=headers, params=page_params, timeout=10)
            if resp.status_code != 200:
                break

            messages = resp.json().get("messages", []) or []
            if not messages:
                break

            for msg in messages:
                if len(results) >= max_total:
                    break
                mid = msg.get("id")
                if not mid:
                    continue

                detail = httpx.get(f"{base}/{mid}", headers=headers, timeout=10)
                if detail.status_code != 200:
                    continue

                body = detail.json()
                snippet = body.get("snippet") or ""
                payload = body.get("payload") or {}
                headers_list = payload.get("headers") or []
                header_map = {h.get("name"): h.get("value") for h in headers_list if h.get("name")}

                results.append({
                    "id": mid,
                    "thread_id": body.get("threadId"),
                    "from": header_map.get("From", "Unknown"),
                    "subject": header_map.get("Subject", "No subject"),
                    "snippet": snippet,
                    "received_at": body.get("internalDate"),
                    "date": header_map.get("Date", ""),
                    "link": f"https://mail.google.com/mail/u/0/#all/{mid}",
                })

            page_token = resp.json().get("nextPageToken")
            if not page_token:
                break

        return results

    except Exception as e:
        print(f"Error fetching emails: {e}")
        return []


def fetch_unread_emails(user: UserORM, db: Session, max_results: int = 500) -> List[Dict]:
    """
    Fetch unread emails for a user (with automatic token refresh)
    
    This is the main function to use - it handles token refresh automatically.
    
    Returns list of dicts with:
    - id: Gmail message ID
    - from: Sender
    - subject: Email subject  
    - snippet: Preview text
    - date: When received
    """

    def _merge_emails_with_cap(existing: list, new: list, cap: int = 500) -> list:
        """Merge emails by ID, preferring newer received_at, capped to 'cap' items."""
        by_id = {}
        for email in existing + new:
            mid = email.get("id") or email.get("message_id") or email.get("thread_id")
            if not mid:
                continue
            prev = by_id.get(mid)
            if not prev:
                by_id[mid] = email
                continue
            try:
                prev_ts = int(prev.get("received_at") or 0)
            except Exception:
                prev_ts = 0
            try:
                new_ts = int(email.get("received_at") or 0)
            except Exception:
                new_ts = 0
            if new_ts >= prev_ts:
                by_id[mid] = email
        merged = list(by_id.values())
        def _ts(e):
            try:
                return int(e.get("received_at") or 0)
            except Exception:
                return 0
        merged.sort(key=_ts, reverse=True)
        return merged[:cap]

    try:
        access_token = _get_valid_token(user, db)
        emails = fetch_unread_emails_raw(access_token, max_total=max_results, days_back=30)

        # Load or create context store to persist seen emails
        context_store = db.query(UserContextStore).filter(UserContextStore.user_id == user.id).first()
        if not context_store:
            context_store = UserContextStore(
                id=str(uuid.uuid4()),
                user_id=user.id,
            )
            db.add(context_store)
            db.commit()
            db.refresh(context_store)

        existing = context_store.emails_recent or []
        merged = _merge_emails_with_cap(existing, emails, cap=max_results)
        context_store.emails_recent = merged
        context_store.last_email_sync = datetime.now(timezone.utc)
        # Keep total_items_cached roughly aligned if other buckets exist
        total_cached = len(merged) + len(context_store.calendar_recent or [])
        context_store.total_items_cached = total_cached
        db.commit()

        unique_emails = set()
        date_values = []

        for email in merged:
            email_id = email.get("id") or email.get("message_id") or email.get("thread_id")
            if email_id:
                unique_emails.add(email_id)

            date_value = email.get("date") or email.get("received_at")
            if date_value:
                date_values.append(str(date_value))

        min_date = min(date_values) if date_values else None
        max_date = max(date_values) if date_values else None

        logger.info(f"[Email Fetch] Fetched {len(emails)} emails for {user.email} | Merged cached: {len(merged)}")
        logger.info(f"[Email Fetch] Unique email IDs: {len(unique_emails)}")
        if min_date and max_date:
            logger.info(f"[Email Fetch] Date range: {min_date} to {max_date}")
        else:
            logger.info("[Email Fetch] Date range: None available")

        return merged
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Gmail] Unexpected error for user {user.id}: {e}", exc_info=True)
        return []


def mark_email_as_read(user: UserORM, message_id: str, db: Session) -> bool:
    """
    Mark a Gmail message as read by removing the UNREAD label.

    This prevents the worker from repeatedly fetching and processing
    the same email after it's been completed in the timeline.

    Args:
        user: User object with Gmail OAuth credentials
        message_id: Gmail message ID (from source_id)
        db: Database session

    Returns:
        True if successful, False otherwise
    """
    try:
        access_token = _get_valid_token(user, db)

        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"https://www.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify"

        # Remove UNREAD label to mark as read
        payload = {"removeLabelIds": ["UNREAD"]}

        resp = httpx.post(url, headers=headers, json=payload, timeout=10)

        if resp.status_code == 200:
            logger.info(f"[Gmail] ✅ Marked message {message_id} as read")
            return True
        else:
            logger.warning(f"[Gmail] Failed to mark message {message_id} as read: HTTP {resp.status_code}")
            return False

    except HTTPException:
        # OAuth errors - let them propagate but return False
        logger.warning(f"[Gmail] OAuth error marking message {message_id} as read")
        return False
    except Exception as e:
        logger.error(f"[Gmail] Error marking message {message_id} as read: {e}")
        return False
