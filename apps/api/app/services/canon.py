import hashlib
import json
import logging
import os
import re
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from logging.handlers import RotatingFileHandler

import pytz

from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models import (
    User as UserORM,
    UserCanonicalPlan,
    CompletedBriefItem,
    Notification as NotificationORM,
)
from app.services import runtime_settings
from app.services.event_emitter import emit_event
from app.services import log_buffer

logger = logging.getLogger(__name__)

class TimelineVerboseFilter(logging.Filter):
    """Gate timeline info logs behind runtime toggle; always allow errors."""

    def filter(self, record: logging.LogRecord) -> bool:
        if "canon" not in record.name:
            return True
        if record.levelno >= logging.ERROR:
            return True
        return bool(runtime_settings.is_timeline_verbose())


logger.addFilter(TimelineVerboseFilter())

# Debug logging configuration
CANON_DEBUG_EMAIL = os.getenv("CANON_DEBUG_EMAIL", "severin.spagnola@sjsu.edu")

# === FILE-BASED LOGGING SETUP ===
# Add rotating file handler for timeline diagnostics
# This solves Render's terrible log viewer by saving logs to a downloadable file
LOG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

timeline_log_file = os.path.join(LOG_DIR, 'timeline_diagnostics.log')

# Rotating file handler (max 10MB, keep 5 backups)
file_handler = RotatingFileHandler(
    timeline_log_file,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)

# Set format with timestamp
file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
file_handler.setFormatter(file_formatter)
file_handler.setLevel(logging.WARNING)  # Capture WARNING and above

# Add to logger
logger.addHandler(file_handler)

logger.warning(f"[File Logging] Timeline diagnostics will be saved to: {timeline_log_file}")


# === IN-MEMORY CACHE FOR ADMIN DEBUG DASHBOARD ===
# Stores latest timeline generation metrics per user for admin endpoints
TIMELINE_DEBUG_CACHE = {}


def _cache_key(user_identifier: str) -> str:
    return (user_identifier or "").strip().lower()


def _init_cache(key: str):
    if key not in TIMELINE_DEBUG_CACHE:
        TIMELINE_DEBUG_CACHE[key] = {
            "stages": {},
            "stages_list": [],
            "stage_items": {},
            "recurring_patterns": [],
            "ai_items_sent": None,
            "ai_excluded": None,
            "validation_fixes": 0,
            "guardrails": {},
            "timestamp": datetime.now().isoformat(),
            "pipeline_totals": {},
            "email_stage_0": {},
        }


def _record_stage(key: str, stage_key: str, label: str, input_count: int, output_count: int, removed_reasons: dict | None = None, duration_ms: int | None = None):
    _init_cache(key)
    removed = max(0, (input_count or 0) - (output_count or 0))
    entry = {
        "stage_key": stage_key,
        "label": label,
        "input_count": input_count,
        "output_count": output_count,
        "removed_count": removed,
    }
    if removed_reasons:
        entry["removed_reasons"] = removed_reasons
    if duration_ms is not None:
        entry["duration_ms"] = duration_ms
    TIMELINE_DEBUG_CACHE[key]["stages_list"].append(entry)
    TIMELINE_DEBUG_CACHE[key]["stages"][stage_key] = {
        "total_items": output_count,
        "timestamp": datetime.now().isoformat(),
    }
    TIMELINE_DEBUG_CACHE[key].setdefault("stage_items", {}).setdefault(stage_key, [])


def _sanitize_item(item: dict) -> dict:
    """Sanitize timeline items for admin debug (no tokens/bodies)."""
    if not isinstance(item, dict):
        return {}
    return {
        "id": item.get("id") or item.get("source_id"),
        "source_type": item.get("source_type"),
        "subject": item.get("subject") or item.get("title") or item.get("summary"),
        "from": item.get("from") or item.get("from_email"),
        "received_at": item.get("received_at") or item.get("start") or item.get("deadline"),
        "deadline": item.get("deadline"),
        "deadline_raw": item.get("deadline_raw"),
        "reason": item.get("reason"),
        "reason_codes": item.get("reason_codes"),
        "signature": item.get("signature"),
        "snippet": (item.get("snippet") or "")[:140] if item.get("snippet") else None,
    }


def cache_stage_data(user_email: str, stage: str, data: dict):
    """
    Cache stage data for admin debug endpoint.
    Stores in-memory metrics about timeline generation stages.
    """
    key = _cache_key(user_email)
    _init_cache(key)
    TIMELINE_DEBUG_CACHE[key]["stages"][stage] = {
        **data,
        "timestamp": datetime.now().isoformat()
    }
    if "stage_items" in data:
        items = data.get("stage_items") or []
        TIMELINE_DEBUG_CACHE[key].setdefault("stage_items", {})[stage] = items


def cache_recurring_pattern(user_email: str, title: str):
    """Cache a recurring pattern detection for admin debug."""
    key = _cache_key(user_email)
    _init_cache(key)
    if title not in TIMELINE_DEBUG_CACHE[key]["recurring_patterns"]:
        TIMELINE_DEBUG_CACHE[key]["recurring_patterns"].append(title)


def cache_ai_stats(user_email: str, items_sent: int, items_returned: int, excluded: int):
    """Cache AI processing stats for admin debug."""
    key = _cache_key(user_email)
    _init_cache(key)

    TIMELINE_DEBUG_CACHE[key]["ai_items_sent"] = items_sent
    TIMELINE_DEBUG_CACHE[key]["ai_items_returned"] = items_returned
    TIMELINE_DEBUG_CACHE[key]["ai_excluded"] = excluded


def cache_validation_fix(user_email: str, count: int):
    """Cache validation fix count for admin debug."""
    key = _cache_key(user_email)
    _init_cache(key)
    TIMELINE_DEBUG_CACHE[key]["validation_fixes"] += count


def cache_guardrail(user_email: str, timeframe: str, count: int, guardrail_type: str):
    """Cache guardrail activation for admin debug."""
    cache_key = _cache_key(user_email)
    _init_cache(cache_key)
    guardrail_key = f"{timeframe}_{guardrail_type}"
    TIMELINE_DEBUG_CACHE[cache_key]["guardrails"][guardrail_key] = count


def get_user_timezone(user: UserORM, db: Session) -> str:
    """Get user's timezone from preferences, default to UTC."""
    prefs = getattr(user, "preferences", None) or {}
    tz = prefs.get("timezone", "UTC")
    try:
        pytz.timezone(tz)
        return tz
    except Exception:
        logger.warning(f"[Canon] Invalid timezone '{tz}' for user {user.id}, using UTC")
        return "UTC"


def calculate_event_deadline(event_time_str: str, user_timezone: str) -> Dict:
    """
    Calculate deadline for an event in user's timezone.
    Returns dict with deadline text, is_past flag, and hours_until.
    """
    try:
        if "T" in (event_time_str or ""):
            event_dt = datetime.fromisoformat(event_time_str.replace("Z", "+00:00"))
        else:
            user_tz = pytz.timezone(user_timezone)
            naive_dt = datetime.fromisoformat(event_time_str)
            event_dt = user_tz.localize(naive_dt)

        user_tz = pytz.timezone(user_timezone)
        now = datetime.now(pytz.UTC).astimezone(user_tz)
        time_until = event_dt - now
        hours_until = time_until.total_seconds() / 3600

        if hours_until < 0:
            hours_ago = abs(hours_until)
            if hours_ago < 1:
                deadline_text = "Just passed"
            elif hours_ago < 24:
                deadline_text = f"{int(hours_ago)} hours ago"
            else:
                deadline_text = f"{int(hours_ago / 24)} days ago"
            is_past = True
        elif hours_until < 1:
            minutes_until = int(time_until.total_seconds() / 60)
            deadline_text = f"Due in {minutes_until} minutes"
            is_past = False
        elif hours_until < 24:
            deadline_text = f"Due in {int(hours_until)} hours"
            is_past = False
        else:
            days_until = int(hours_until / 24)
            deadline_text = f"Due in {days_until} days"
            is_past = False

        return {
            "deadline_text": deadline_text,
            "is_past": is_past,
            "hours_until": hours_until,
        }
    except Exception as e:
        logger.error(f"[Canon] Error calculating deadline for '{event_time_str}': {e}")
        return {"deadline_text": "Invalid date", "is_past": False, "hours_until": 0}


def generate_item_signature(item: Dict) -> str:
    """
    Generate deterministic signature for timeline items.
    Uses source_id as primary key to ensure consistency across refreshes.

    This is the SINGLE SOURCE OF TRUTH for signature generation.
    Used everywhere: AI generation, completion, deletion, filtering.

    Args:
        item: Timeline item dict with source_id, source_type, title, etc.

    Returns:
        MD5 hash string
    """
    # Normalize inputs
    source_id = (item.get("source_id") or item.get("id") or "").strip()
    source_type = (item.get("source_type") or "").strip().lower()

    # Primary: Use source_id if available (Gmail message ID, Calendar event ID)
    if source_id and source_type:
        sig_input = f"{source_type}:{source_id}"
        logger.debug(f"[Signature] Generated from source: {sig_input}")
    else:
        # Fallback: Use normalized title
        title = (item.get("title") or item.get("subject") or item.get("summary") or "").strip()
        normalized_title = " ".join(title.split())  # Normalize whitespace
        sig_input = f"{source_type}:{normalized_title}" if source_type else f"title:{normalized_title}"
        logger.debug(f"[Signature] Generated from title: {sig_input}")

    signature = hashlib.md5(sig_input.encode()).hexdigest()
    logger.debug(f"[Signature] Final hash: {signature}")
    return signature


def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two text strings using simple token-based matching.
    Returns 0.0 (completely different) to 1.0 (identical).
    """
    if not text1 or not text2:
        return 0.0

    # Normalize
    t1 = text1.lower().strip()
    t2 = text2.lower().strip()

    if t1 == t2:
        return 1.0

    # Tokenize and create sets
    tokens1 = set(re.findall(r'\w+', t1))
    tokens2 = set(re.findall(r'\w+', t2))

    if not tokens1 or not tokens2:
        return 0.0

    # Jaccard similarity
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)

    return intersection / union if union > 0 else 0.0


def parse_datetime(value):
    """
    Parse various datetime formats into a timezone-aware datetime when possible.
    """
    from datetime import datetime

    if value is None:
        raise ValueError("No datetime value provided")

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if isinstance(value, (int, float)):
        # Assume Unix timestamp in seconds (or ms if very large)
        try:
            if value > 1e12:  # likely ms
                value = value / 1000.0
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except Exception as e:
            raise ValueError(f"Could not parse timestamp {value}: {e}")

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception as e:
            raise ValueError(f"Could not parse datetime string '{value}': {e}")

    raise ValueError(f"Unsupported datetime type: {type(value)}")


def deduplicate_by_source_id(items: List[Dict]) -> List[Dict]:
    """
    Remove exact duplicates based on source_id + source_type.
    Must run BEFORE similarity-based deduplication.

    This prevents the same calendar event (same event ID) from appearing multiple times
    if the AI generates it in different passes.

    Args:
        items: List of timeline items (emails + calendar events)

    Returns:
        Deduplicated list (keeps first occurrence of each unique source_id)
    """
    logger.info(f"[Dedup Source ID] Starting with {len(items)} items")

    seen_keys = set()
    deduplicated = []
    removed = []

    for item in items:
        source_id = item.get("source_id") or item.get("id")
        source_type = item.get("source_type", "unknown")
        title = item.get("title", item.get("summary", ""))

        if source_id:
            key = f"{source_type}:{source_id}"
        else:
            deadline = item.get("deadline") or item.get("start") or item.get("start_time") or ""
            key = f"title:{title}:deadline:{deadline}"
            logger.warning(f"[Dedup] No source_id for '{title}', using fallback key")

        if key in seen_keys:
            removed.append(
                {
                    "title": title,
                    "reason": "Duplicate source_id",
                    "key": key,
                }
            )
            continue

        seen_keys.add(key)
        deduplicated.append(item)

    if removed:
        logger.info(f"[Dedup Source ID] REMOVED {len(removed)} duplicates:")
        for r in removed[:5]:
            logger.info(f"  - {r['title']} ({r['reason']})")
        if len(removed) > 5:
            logger.info(f"  ... and {len(removed) - 5} more")

    logger.info(f"[Dedup Source ID] Result: {len(items)} → {len(deduplicated)} items")
    return deduplicated


def deduplicate_similar_events(events: List[Dict], similarity_threshold: float = 0.7) -> List[Dict]:
    """
    Remove duplicate events based on title/summary similarity and time proximity.
    Useful for detecting events like:
    - "Supabase Security Issue" appearing 3 times
    - "Fix the bug" and "Fix bug" at similar times
    """
    if not events:
        return []

    # Group events by approximate time (within 1 hour window)
    time_groups: Dict[str, List[Dict]] = {}

    for event in events:
        event_time_str = event.get("start_time") or event.get("start") or ""
        if not event_time_str:
            # No time - add to special group
            time_groups.setdefault("no_time", []).append(event)
            continue

        try:
            # Parse time and round to nearest hour for grouping
            if "T" in event_time_str:
                event_dt = datetime.fromisoformat(event_time_str.replace("Z", "+00:00"))
            else:
                event_dt = datetime.fromisoformat(event_time_str)

            # Round to nearest hour
            hour_key = event_dt.strftime("%Y-%m-%d-%H")
            time_groups.setdefault(hour_key, []).append(event)
        except Exception:
            time_groups.setdefault("invalid_time", []).append(event)

    deduplicated: List[Dict] = []
    total_removed = 0

    for time_key, group_events in time_groups.items():
        if len(group_events) == 1:
            deduplicated.append(group_events[0])
            continue

        # Within each time group, remove similar events
        kept_events = []
        for event in group_events:
            event_title = (event.get("title") or event.get("summary") or "").strip()

            # Check if similar to any already kept event
            is_duplicate = False
            for kept_event in kept_events:
                kept_title = (kept_event.get("title") or kept_event.get("summary") or "").strip()
                similarity = calculate_text_similarity(event_title, kept_title)

                if similarity >= similarity_threshold:
                    is_duplicate = True
                    total_removed += 1
                    logger.info(
                        f"[Canon Dedup] Removed duplicate event '{event_title}' "
                        f"(similar to '{kept_title}', similarity: {similarity:.2f})"
                    )
                    break

            if not is_duplicate:
                kept_events.append(event)

        deduplicated.extend(kept_events)

    logger.info(f"[Canon Dedup] Smart deduplication: {len(events)} -> {len(deduplicated)} ({total_removed} duplicates removed)")
    return deduplicated


def deduplicate_prep_events(events: List[Dict]) -> List[Dict]:
    """
    Remove duplicate "Prepare for X" events when main event "X" exists at same time.
    """
    events_by_time: Dict[str, List[Dict]] = {}
    for event in events:
        key = event.get("start_time") or event.get("start") or ""
        events_by_time.setdefault(key, []).append(event)

    deduplicated: List[Dict] = []
    for time_slot, slot_events in events_by_time.items():
        if len(slot_events) == 1:
            deduplicated.append(slot_events[0])
            continue

        main_events = []
        prep_events = []
        for event in slot_events:
            title = (event.get("title") or event.get("summary") or "").lower()
            if title.startswith("prepare for "):
                prep_events.append(event)
            else:
                main_events.append(event)

        added_main = set()
        for main_event in main_events:
            main_title = (main_event.get("title") or main_event.get("summary") or "").lower()
            has_prep = any(
                (prep.get("title") or prep.get("summary") or "").lower()
                == f"prepare for {main_title}"
                for prep in prep_events
            )
            if has_prep:
                logger.debug(f"[Canon] Removed duplicate prep event for: {main_event.get('title')}")
            deduplicated.append(main_event)
            added_main.add(main_title)

        for prep in prep_events:
            prep_title = (prep.get("title") or prep.get("summary") or "").lower()
            main_title = prep_title.replace("prepare for ", "")
            if main_title not in added_main:
                deduplicated.append(prep)

    logger.info(f"[Canon] Deduplicated prep events: {len(events)} -> {len(deduplicated)}")
    return deduplicated


def deduplicate_by_semantics(items: List[Dict], threshold: float = 0.90) -> List[Dict]:
    """
    Remove semantically similar items using OpenAI embeddings.

    This catches duplicates that slip through source_id and title similarity checks,
    like "Trade with Chase" vs "Trading session with Chase".

    Args:
        items: List of timeline items
        threshold: Similarity threshold (0.90 = 90% similar)

    Returns:
        Deduplicated list
    """
    if len(items) <= 1:
        return items

    try:
        from openai import OpenAI
        import numpy as np
        import os
        from collections import defaultdict

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        logger.info(f"[Semantic Dedup] Starting with {len(items)} items")

        # Detect recurring instances: same title but different start/deadline times
        title_groups = defaultdict(list)
        for idx, item in enumerate(items):
            title = (item.get("title") or item.get("summary") or "").strip().lower()
            if title:
                title_groups[title].append(idx)

        recurring_indices = set()
        for _, indices in title_groups.items():
            if len(indices) < 2:
                continue
            start_times = set()
            for i in indices:
                inst = items[i]
                start_value = inst.get("start") or inst.get("start_time") or inst.get("deadline")
                if start_value:
                    start_times.add(str(start_value))
            if len(start_times) > 1:
                recurring_indices.update(indices)

        logger.warning(f"[Semantic Dedup] Found {len(recurring_indices)} recurring event instances (same title, different times)")

        # Generate embeddings for all items
        embeddings = []
        for item in items:
            # Combine title and description for better matching
            text = f"{item.get('title', '')} {item.get('description', '')}"
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )
            embeddings.append(np.array(response.data[0].embedding))

        # Find duplicates using cosine similarity
        to_remove = set()
        for i in range(len(items)):
            if i in to_remove:
                continue
            # Never deduplicate recurring items
            if i in recurring_indices:
                continue
            for j in range(i + 1, len(items)):
                if j in to_remove:
                    continue
                if j in recurring_indices:
                    continue

                # Cosine similarity
                similarity = np.dot(embeddings[i], embeddings[j]) / (
                    np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[j])
                )

                if similarity >= threshold:
                    logger.info(
                        f"[Semantic Dedup] ❌ Removing: '{items[j].get('title')}' "
                        f"(similar to '{items[i].get('title')}', score: {similarity:.3f})"
                    )
                    to_remove.add(j)

        result = [item for idx, item in enumerate(items) if idx not in to_remove]

        if len(to_remove) > 0:
            logger.info(f"[Semantic Dedup] Removed {len(to_remove)} semantically similar item(s)")
        logger.warning(f"[Semantic Dedup] Output: {len(result)} items (kept {len(recurring_indices)} recurring intact)")

        return result

    except Exception as e:
        logger.error(f"[Semantic Dedup] Failed: {e}")
        return items  # Return original on error


def analyze_recurring_event_pattern(
    user_id: str,
    item_title: str,
    db: Session,
    days_lookback: int = 30
) -> Dict:
    """
    Analyze user's interaction pattern with events matching a specific TITLE.

    CRITICAL TWO-LEVEL SYSTEM:
    1. Deletion is tracked per SIGNATURE (each unique event instance is deleted individually)
    2. Learning/filtering is by TITLE (if you delete 3+ "Actionable time" events at different times,
       we learn you don't want ANY "Actionable time" events)

    This allows smart learning across similar events while respecting individual deletions.

    Returns:
        {
            "should_filter": bool,
            "reason": str,
            "stats": {
                "total_occurrences": int,
                "completed_count": int,
                "deleted_count": int,
                "deletion_rate": float
            },
            "suggestion": str or None  # Message to show user
        }
    """
    from datetime import timedelta

    # Get history for ALL EVENTS with this TITLE (last N days)
    # This allows learning: "User deletes 'Actionable time' events in general"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_lookback)

    history = db.query(CompletedBriefItem).filter(
        CompletedBriefItem.user_id == user_id,
        CompletedBriefItem.item_title == item_title,
        CompletedBriefItem.completed_at >= cutoff
    ).all()

    if len(history) < 3:
        # Not enough data to establish pattern
        return {
            "should_filter": False,
            "reason": "Insufficient history (< 3 occurrences)",
            "stats": {
                "total_occurrences": len(history),
                "completed_count": 0,
                "deleted_count": 0,
                "deletion_rate": 0.0
            },
            "suggestion": None
        }

    # Count completions vs deletions
    completed_count = sum(1 for h in history if h.action == "completed")
    deleted_count = sum(1 for h in history if h.action == "deleted")
    total = len(history)
    deletion_rate = deleted_count / total if total > 0 else 0

    # Decision thresholds
    should_filter = False
    reason = ""
    suggestion = None

    if deletion_rate >= 0.8 and deleted_count >= 3:
        # User deletes this >80% of the time - auto-filter
        should_filter = True
        reason = f"User deletes '{item_title}' {deletion_rate:.0%} of the time ({deleted_count}/{total})"
        suggestion = f"I noticed you often skip '{item_title}'. I've stopped showing it. You can re-enable it in Settings."

    elif deletion_rate >= 0.6 and deleted_count >= 3:
        # User deletes this >60% of the time - suggest filtering
        should_filter = False
        reason = f"User frequently deletes '{item_title}' ({deletion_rate:.0%})"
        suggestion = f"I noticed you often delete '{item_title}'. Would you like me to stop showing it?"

    return {
        "should_filter": should_filter,
        "reason": reason,
        "stats": {
            "total_occurrences": total,
            "completed_count": completed_count,
            "deleted_count": deleted_count,
            "deletion_rate": deletion_rate
        },
        "suggestion": suggestion
    }


def filter_by_deletion_patterns(items: List[Dict], user_id: str, db: Session) -> List[Dict]:
    """
    Filter out recurring events that user consistently deletes.
    Respects both manual filter list and whitelist from preferences.

    CRITICAL TWO-LEVEL SYSTEM:
    1. Individual deletions track by SIGNATURE (you delete one specific "Actionable time" at 12:30 PM)
    2. Learning/filtering by TITLE (if you delete 3+ different "Actionable time" events,
       we stop showing ALL "Actionable time" events)

    This allows the system to learn patterns across similar events.
    """
    # Get user's filter lists
    user = db.query(UserORM).filter(UserORM.id == user_id).first()
    if not user:
        return items

    prefs = user.preferences or {}
    whitelisted = prefs.get("whitelisted_recurring_events", [])
    manually_filtered = prefs.get("filtered_recurring_events", [])

    logger.info(f"[Filter] Checking {len(items)} items against filter list")
    logger.info(f"[Filter] User's filter list: {manually_filtered}")
    logger.info(f"[Filter] Whitelisted recurring events: {whitelisted}")
    if not manually_filtered:
        logger.info("[Filter] No manual filters active")

    filtered_items = []
    filtered_count = 0
    filtered_out = []
    auto_filtered = []

    for item in items:
        title = item.get("title", "")

        # Skip empty titles
        if not title:
            filtered_items.append(item)
            continue

        # Skip filtering if user explicitly whitelisted this
        if title in whitelisted:
            filtered_items.append(item)
            continue

        # CRITICAL: Check manual filter list FIRST
        if title in manually_filtered:
            logger.info(f"[Manual Filter] Hiding '{title}' - in user's filter list")
            filtered_count += 1
            filtered_out.append(title)
            continue

        # Check if events with this TITLE should be auto-filtered (based on deletion history)
        pattern = analyze_recurring_event_pattern(user_id, title, db)

        if pattern["should_filter"]:
            logger.info(f"[Auto Filter] Filtering '{title}': {pattern['reason']}")
            filtered_count += 1
            auto_filtered.append(title)

            # Store suggestion for user notification if needed
            if pattern["suggestion"]:
                # You could create a notification here
                pass
        else:
            filtered_items.append(item)

    if filtered_count > 0:
        logger.info(f"[Smart Filter] Removed {filtered_count} low-value recurring events")
    if filtered_out:
        logger.info(f"[Filter] FILTERED OUT: {set(filtered_out)}")
    if auto_filtered:
        logger.info(f"[Filter] AUTO-FILTERED: {set(auto_filtered)}")
    logger.info(f"[Filter] Result: {len(items)} → {len(filtered_items)} items")

    return filtered_items


def _get_item_datetime_for_sort(item: Dict, user_tz: pytz.timezone) -> Optional[datetime]:
    """Best-effort datetime extractor for ranking/backfill."""
    for key in ['deadline_raw', 'start_time', 'start', 'deadline', 'received_at', 'date']:
        value = item.get(key)
        if not value:
            continue
        try:
            dt = parse_datetime(value)
            return dt.astimezone(user_tz)
        except Exception:
            continue
    return None


def stabilize_timeline_output(
    ai_timeline: dict,
    candidate_items: List[Dict],
    user_tz: pytz.timezone,
    min_per_timeframe: Dict[str, int],
    max_per_timeframe: Dict[str, int],
    today: datetime.date,
    week_end: datetime.date,
    month_end: datetime.date,
) -> dict:
    """
    Enforce small minimums and caps per timeframe, backfilling with nearest upcoming items.
    """
    stabilized = {tf: {"urgent": [], "normal": []} for tf in ['1d', '7d', '28d']}

    def timeframe_for_date(d: datetime.date) -> Optional[str]:
        if d == today:
            return '1d'
        if today < d <= week_end:
            return '7d'
        if week_end < d <= month_end:
            return '28d'
        return None

    # Carry over AI output
    existing_sigs = set()
    for tf in ['1d', '7d', '28d']:
        tf_data = ai_timeline.get(tf, {}) if isinstance(ai_timeline, dict) else {}
        for section in ['urgent', 'normal']:
            items = tf_data.get(section, []) if isinstance(tf_data, dict) else []
            for item in items:
                sig = item.get("signature") or generate_item_signature(item)
                if sig in existing_sigs:
                    continue
                existing_sigs.add(sig)
                stabilized[tf][section].append(item)

    # Preprocess candidates by timeframe
    candidate_by_tf = {"1d": [], "7d": [], "28d": []}
    for item in candidate_items:
        sig = item.get("signature") or generate_item_signature(item)
        if sig in existing_sigs:
            continue
        dt = _get_item_datetime_for_sort(item, user_tz)
        if not dt:
            continue
        tf = timeframe_for_date(dt.date())
        if not tf:
            continue
        candidate_by_tf[tf].append((dt, item))

    # Sort candidates soonest first
    for tf in candidate_by_tf:
        candidate_by_tf[tf].sort(key=lambda x: x[0])

    # Enforce minimums by backfilling into normal
    for tf in ['1d', '7d', '28d']:
        min_needed = max(0, min_per_timeframe.get(tf, 0) - (len(stabilized[tf]['urgent']) + len(stabilized[tf]['normal'])))
        if min_needed <= 0:
            continue
        candidates = candidate_by_tf.get(tf, [])
        for _, item in candidates[:min_needed]:
            sig = item.get("signature") or generate_item_signature(item)
            if sig in existing_sigs:
                continue
            existing_sigs.add(sig)
            stabilized[tf]['normal'].append(item)

    # Apply caps (keep urgent first, then earliest normals)
    for tf in ['1d', '7d', '28d']:
        cap = max_per_timeframe.get(tf, 999)
        urgent = stabilized[tf]['urgent']
        normal = stabilized[tf]['normal']
        # Sort normals by datetime
        normal_sorted = []
        for item in normal:
            dt = _get_item_datetime_for_sort(item, user_tz)
            normal_sorted.append((dt or datetime.max.replace(tzinfo=timezone.utc), item))
        normal_sorted.sort(key=lambda x: x[0])
        merged = urgent + [it for _, it in normal_sorted]
        if len(merged) > cap:
            merged = merged[:cap]
        # Split back, keeping urgent first then normals
        stabilized[tf]['urgent'] = urgent  # keep original order
        stabilized[tf]['normal'] = [it for it in merged if it not in urgent]

    # Special case: if 1d is empty but we have near-term items, force-fill
    if len(stabilized['1d']['urgent']) + len(stabilized['1d']['normal']) == 0:
        logger.warning("[Guardrails] 🚨 1d is empty, attempting force-fill with next 24h items")
        now = datetime.now(user_tz)
        cutoff = now + timedelta(hours=24)
        near_term = []
        for item in candidate_items:
            dt = _get_item_datetime_for_sort(item, user_tz)
            if not dt:
                continue
            if now <= dt <= cutoff:
                near_term.append((dt, item))
        near_term.sort(key=lambda x: x[0])
        added = 0
        for _, item in near_term[:max_per_timeframe.get('1d', 5)]:
            sig = item.get("signature") or generate_item_signature(item)
            if sig in existing_sigs:
                continue
            existing_sigs.add(sig)
            stabilized['1d']['normal'].append(item)
            added += 1
        logger.warning(f"[Guardrails] ✅ Force-filled 1d with {added} item(s)")

        # Cache guardrail activation for admin debug
        # Note: We need user email, but it's not available in this function scope
        # The cache will be called from the main generate_recommendations function

    return stabilized


def validate_and_fix_categorization(timeline: dict, user_timezone: str) -> dict:
    """
    Fix AI categorization mistakes by re-categorizing based on actual dates.

    The AI sometimes puts tomorrow's events in 28d (Monthly) instead of 7d (Weekly).
    This function validates each item's deadline and moves it to the correct timeframe.

    Args:
        timeline: AI-generated timeline dict
        user_timezone: User's timezone (e.g., "America/Los_Angeles")

    Returns:
        Fixed timeline with correct categorization
    """
    from datetime import datetime, timedelta
    import pytz

    user_tz = pytz.timezone(user_timezone)
    now = datetime.now(user_tz)
    today = now.date()
    week_end = today + timedelta(days=7)
    month_end = today + timedelta(days=28)

    logger.info(f"[Validation] ════════════════════════════════════════════════════════")
    logger.info(f"[Validation] Starting categorization validation")
    logger.info(f"[Validation] Today: {today}, Week ends: {week_end}, Month ends: {month_end}")

    # Collect all items with original categorization
    all_items = []
    for timeframe in ['1d', '7d', '28d']:
        for priority in ['urgent', 'normal']:
            items = timeline.get(timeframe, {}).get(priority, [])
            logger.info(f"[Validation] AI categorized {len(items)} items in {timeframe}/{priority}")
            for item in items:
                all_items.append({
                    **item,
                    '_original_timeframe': timeframe,
                    '_original_priority': priority
                })

    logger.info(f"[Validation] Total items to validate: {len(all_items)}")

    # Re-categorize based on actual dates
    new_timeline = {
        '1d': {'urgent': [], 'normal': []},
        '7d': {'urgent': [], 'normal': []},
        '28d': {'urgent': [], 'normal': []}
    }

    fixes = 0

    for item in all_items:
        # Get item date from various possible fields
        deadline = item.get('deadline_raw') or item.get('deadline') or item.get('start') or item.get('due_time') or item.get('start_time')

        if not deadline:
            # No date - keep original categorization
            orig_tf = item.pop('_original_timeframe')
            orig_pr = item.pop('_original_priority')
            new_timeline[orig_tf][orig_pr].append(item)
            continue

        try:
            # Parse date
            if isinstance(deadline, str) and re.match(r'^\d{4}-\d{2}-\d{2}', deadline):
                item_datetime = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
            else:
                raise ValueError("Non-ISO deadline format")
            item_date = item_datetime.astimezone(user_tz).date()
        except Exception as e:
            logger.warning(f"[Validation] Invalid date '{deadline}' for '{item.get('title')}': {e}")
            orig_tf = item.pop('_original_timeframe')
            orig_pr = item.pop('_original_priority')
            new_timeline[orig_tf][orig_pr].append(item)
            continue

        # Determine correct timeframe based on actual date
        if item_date == today:
            correct_timeframe = '1d'
        elif item_date <= week_end:
            correct_timeframe = '7d'
        elif item_date <= month_end:
            correct_timeframe = '28d'
        else:
            # Beyond 28 days - skip
            logger.info(f"[Validation] Skipping item beyond 28 days: {item.get('title')} ({item_date})")
            continue

        # Check if AI was wrong
        orig_tf = item.pop('_original_timeframe')
        orig_pr = item.pop('_original_priority')

        # Enhanced logging for debugging
        title = item.get('title', 'unknown')
        if correct_timeframe != orig_tf:
            fixes += 1
            logger.warning(
                f"[Validation] ⚠️  FIXED MISCATEGORIZATION: '{title}' "
                f"| Date: {item_date} ({deadline}) "
                f"| AI put in: {orig_tf} "
                f"| Correct: {correct_timeframe} "
                f"| Reason: {item_date} vs today={today}"
            )
        else:
            logger.debug(
                f"[Validation] ✅ Correct: '{title}' "
                f"| Date: {item_date} | Timeframe: {correct_timeframe}"
            )

        new_timeline[correct_timeframe][orig_pr].append(item)

    logger.info(f"[Validation] ════════════════════════════════════════════════════════")
    if fixes > 0:
        logger.warning(f"[Validation] ⚠️  Fixed {fixes} mis-categorized item(s)")
    else:
        logger.info(f"[Validation] ✅ All items correctly categorized by AI")
    logger.info(f"[Validation] Final timeline: 1d={len(new_timeline['1d']['urgent']) + len(new_timeline['1d']['normal'])}, 7d={len(new_timeline['7d']['urgent']) + len(new_timeline['7d']['normal'])}, 28d={len(new_timeline['28d']['urgent']) + len(new_timeline['28d']['normal'])}")
    logger.info(f"[Validation] ════════════════════════════════════════════════════════")

    return new_timeline


def merge_and_dedupe(existing: list, new: list) -> list:
    by_id = {}
    for item in existing + new:
        item_id = item.get("id")
        if not item_id:
            continue
        prev = by_id.get(item_id)
        if not prev:
            by_id[item_id] = item
        else:
            prev_date = prev.get("date") or prev.get("start") or ""
            new_date = item.get("date") or item.get("start") or ""
            if new_date > prev_date:
                by_id[item_id] = item
    merged = list(by_id.values())
    merged.sort(key=lambda x: (x.get("date") or x.get("start") or ""), reverse=True)
    return merged


def migrate_timeline_to_2tier(timeline: Dict) -> Dict:
    """
    Convert old 3-tier schema to new 2-tier schema.
    Maps:
      - critical → urgent
      - high/high_priority/medium → normal
      - normal/low/upcoming/milestones/goals → normal

    Args:
        timeline: Old timeline dict with mixed priority levels

    Returns:
        New timeline dict with only 'urgent' and 'normal' sections
    """
    new_timeline = {}

    for timeframe in ["1d", "7d", "28d"]:
        old_section = timeline.get(timeframe, {})

        # Urgent: only critical items
        urgent_items = old_section.get("critical", [])

        # Normal: everything else
        normal_items = []
        for key in ["high", "high_priority", "medium", "normal", "low", "upcoming", "milestones", "goals", "progress"]:
            items = old_section.get(key, [])
            if isinstance(items, list):
                normal_items.extend(items)
            # Skip 'progress' if it's a dict

        new_timeline[timeframe] = {
            "urgent": urgent_items,
            "normal": normal_items
        }

        logger.debug(f"[Migration] {timeframe}: {len(urgent_items)} urgent, {len(normal_items)} normal")

    logger.info(f"[Migration] Migrated timeline from old schema to 2-tier (urgent/normal)")
    return new_timeline


def detect_recurring_pattern(items: List[Dict]) -> Optional[Dict]:
    """
    Detect if a group of items forms a recurring pattern.

    Args:
        items: List of items with same title

    Returns:
        Pattern dict if recurring pattern detected, None otherwise
        {
            "type": "daily" | "weekly" | "custom",
            "time": "06:30:00",
            "days": ["Mon", "Tue", "Wed", "Thu", "Fri"] or None for daily,
            "next_occurrence": "2025-12-31T06:30:00-08:00",
            "instance_count": 5,
            "instances": [list of all instance dicts]
        }
    """
    logger.warning(f"[Recurring Debug] === Checking recurring for '{items[0].get('title', 'UNKNOWN') if items else 'NONE'}' ===")
    logger.warning(f"[Recurring Debug] Input instances: {len(items)}")
    for idx, itm in enumerate(items, 1):
        logger.warning(
            f"[Recurring Debug] Instance {idx}: "
            f"deadline_raw={itm.get('deadline_raw')} | "
            f"start={itm.get('start')} | "
            f"deadline={itm.get('deadline')} | "
            f"start_time={itm.get('start_time')}"
        )

    if len(items) < 2:
        logger.info(f"[Recurring] '{items[0].get('title') if items else 'UNKNOWN'}': Only 1 instance, not recurring")
        return None

    try:
        logger.info(f"[Recurring] Checking '{items[0].get('title', 'UNKNOWN')}': {len(items)} instances")

        # Parse all deadlines (prefer raw values to avoid formatted strings)
        parsed_items = []
        for idx, item in enumerate(items, 1):
            time_value = (
                item.get('deadline_raw') or
                item.get('start_time') or
                item.get('start') or
                item.get('deadline')
            )
            logger.info(f"  Instance {idx}: {time_value}")
            if not time_value:
                continue
            try:
                dt = parse_datetime(time_value)
                parsed_items.append({'item': item, 'datetime': dt})
            except Exception:
                continue

        if len(parsed_items) < 2:
            logger.info(f"[Recurring] NO PATTERN: Not enough parseable timestamps")
            return None

        # Sort by datetime
        parsed_items.sort(key=lambda x: x['datetime'])

        # Extract times (HH:MM:SS)
        times = [item['datetime'].time() for item in parsed_items]

        # Check if all times are the same (within 5 minute tolerance)
        first_time = times[0]
        time_matches = all(
            abs((t.hour * 60 + t.minute) - (first_time.hour * 60 + first_time.minute)) <= 5
            for t in times
        )

        if not time_matches:
            logger.info(f"[Recurring] NO PATTERN: Times don't match or dates not consecutive")
            return None  # Different times, not a recurring pattern

        # SIMPLIFIED APPROACH: If 2+ events at similar time, consider recurring
        # This catches daily, weekly, and any other pattern without strict date checking

        dates = [item['datetime'].date() for item in parsed_items]
        weekdays = [d.weekday() for d in dates]  # 0=Mon, 6=Sun
        unique_dates = set(dates)

        # Require at least two distinct dates to treat as recurring
        if len(unique_dates) < 2:
            logger.info(f"[Recurring] NO PATTERN: Less than 2 unique dates")
            return None

        # With 2+ instances at same time, determine pattern type
        if len(parsed_items) >= 2:
            deltas = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]

            # Daily pattern: all deltas are 1 day
            if all(d == 1 for d in deltas):
                result = {
                    "type": "daily",
                    "time": first_time.strftime("%H:%M:%S"),
                    "days": None,
                    "next_occurrence": parsed_items[0]['item'].get('deadline'),
                    "instance_count": len(parsed_items),
                    "instances": [p['item'] for p in parsed_items]
                }
                logger.info(f"[Recurring] PATTERN FOUND: daily at {result['time']}")
                logger.info(f"[Recurring] Consolidating {len(parsed_items)} instances")
                logger.warning(f"[Recurring Debug] ✅ PATTERN DETECTED for '{items[0].get('title', 'UNKNOWN')}': daily | instances={len(parsed_items)}")
                return result

            # Weekday pattern: all on weekdays, with 1 or 3 day gaps (consecutive weekdays)
            if all(wd < 5 for wd in weekdays):  # All weekdays
                is_consecutive_weekdays = all(d in [1, 3] for d in deltas)
                if is_consecutive_weekdays:
                    result = {
                        "type": "weekly",
                        "time": first_time.strftime("%H:%M:%S"),
                        "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                        "next_occurrence": parsed_items[0]['item'].get('deadline'),
                        "instance_count": len(parsed_items),
                        "instances": [p['item'] for p in parsed_items]
                    }
                    logger.info(f"[Recurring] PATTERN FOUND: weekly weekdays at {result['time']}")
                    logger.info(f"[Recurring] Consolidating {len(parsed_items)} instances")
                    logger.warning(f"[Recurring Debug] ✅ PATTERN DETECTED for '{items[0].get('title', 'UNKNOWN')}': weekly-weekdays | instances={len(parsed_items)}")
                    return result

            # Specific days pattern: recurring on specific weekdays
            unique_weekdays = sorted(set(weekdays))
            if 2 <= len(unique_weekdays) <= 5 and len(set(deltas)) <= 3:
                day_names_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                day_names = [day_names_map[wd] for wd in unique_weekdays]
                result = {
                    "type": "weekly",
                    "time": first_time.strftime("%H:%M:%S"),
                    "days": day_names,
                    "next_occurrence": parsed_items[0]['item'].get('deadline'),
                    "instance_count": len(parsed_items),
                    "instances": [p['item'] for p in parsed_items]
                }
                logger.info(f"[Recurring] PATTERN FOUND: weekly ({', '.join(day_names)}) at {result['time']}")
                logger.info(f"[Recurring] Consolidating {len(parsed_items)} instances")
                logger.warning(f"[Recurring Debug] ✅ PATTERN DETECTED for '{items[0].get('title', 'UNKNOWN')}': weekly-specific | instances={len(parsed_items)}")
                return result

            # Generic recurring: 2+ instances at same time, any date pattern
            # This catches everything else - weekly on same day, biweekly, etc.
            result = {
                "type": "custom",
                "time": first_time.strftime("%H:%M:%S"),
                "days": None,
                "next_occurrence": parsed_items[0]['item'].get('deadline'),
                "instance_count": len(parsed_items),
                "instances": [p['item'] for p in parsed_items]
            }
            logger.info(f"[Recurring] PATTERN FOUND: custom at {result['time']}")
            logger.info(f"[Recurring] Consolidating {len(parsed_items)} instances")
            logger.warning(f"[Recurring Debug] ✅ PATTERN DETECTED for '{items[0].get('title', 'UNKNOWN')}': custom | instances={len(parsed_items)}")
            return result

        logger.info(f"[Recurring] NO PATTERN: Times don't match or dates not consecutive")
        logger.warning(f"[Recurring Debug] ❌ NO PATTERN for '{items[0].get('title', 'UNKNOWN')}': time_matches={time_matches}, unique_dates={len(unique_dates)}")
        return None

    except Exception as e:
        logger.error(f"[Recurring Detection] Error detecting pattern: {e}")
        logger.warning(f"[Recurring Debug] ❌ NO PATTERN for '{items[0].get('title', 'UNKNOWN') if items else 'UNKNOWN'}': exception {e}")
        return None


def consolidate_recurring_events(items: List[Dict]) -> List[Dict]:
    """
    Consolidate recurring events into single items with recurrence info.
    Non-recurring events are returned as-is.

    Args:
        items: List of timeline items

    Returns:
        Consolidated list with recurring events grouped
    """
    from collections import defaultdict

    logger.warning(f"[Consolidate Debug] Input items: {len(items)}")

    # Group by title (case-insensitive, normalized)
    groups = defaultdict(list)
    for item in items:
        title = (item.get('title') or '').strip().lower()
        if title:
            groups[title].append(item)

    logger.info(f"[Recurring] Analyzing {len(groups)} unique titles for patterns")
    for g_title, g_items in groups.items():
        if len(g_items) > 1:
            logger.warning(f"[Consolidate Debug] Title '{g_title}': {len(g_items)} instance(s)")

    consolidated = []

    for title, group_items in groups.items():
        if len(group_items) == 1:
            # Single item, no consolidation needed
            consolidated.append(group_items[0])
            continue

        logger.info(f"[Recurring] Checking '{title}': {len(group_items)} instances")
        # Log deadlines and signatures for debugging
        for item in group_items:
            deadline = item.get('deadline') or item.get('start_time') or item.get('start')
            sig = item.get('signature', 'no-sig')[:8]
            logger.info(f"[Recurring]   - {deadline} (sig: {sig}...)")

        # Check for recurring pattern
        logger.warning(f"[Consolidate Debug] Calling detect_recurring_pattern for '{title}' with {len(group_items)} instances")
        pattern = detect_recurring_pattern(group_items)
        logger.warning(f"[Consolidate Debug] Pattern result for '{title}': {pattern}")

        if pattern:
            logger.info(f"[Recurring] ✅ PATTERN DETECTED: {pattern['type']} - {pattern.get('time')} - {len(pattern['instances'])} instances")
            logger.warning(f"[Consolidate Debug] ✅ Creating consolidated event for '{title}'")
        else:
            logger.info(f"[Recurring] ❌ NO PATTERN: Likely different times or insufficient instances")

        if pattern:
            # Consolidate into recurring event
            first_item = pattern['instances'][0]

            # Format recurrence description
            if pattern['type'] == 'daily':
                recurrence_desc = f"Daily at {pattern['time'][:5]}"  # HH:MM
            elif pattern['type'] == 'weekly' and pattern['days']:
                days_str = ''.join([d[0] for d in pattern['days']])  # MTWTF
                recurrence_desc = f"{days_str} at {pattern['time'][:5]}"
            else:
                recurrence_desc = f"Recurring at {pattern['time'][:5]}"

            # Create consolidated item
            # Update title to show recurrence pattern for clarity
            original_title = first_item.get('title', '')

            # Build human-readable list of upcoming dates
            upcoming_dates: List[str] = []
            upcoming_date_objs = []
            for instance in pattern['instances']:
                raw_time = (
                    instance.get('deadline_raw') or
                    instance.get('start_time') or
                    instance.get('start') or
                    instance.get('deadline')
                )
                if raw_time:
                    try:
                        dt = parse_datetime(raw_time)
                        upcoming_date_objs.append(dt.date())
                    except Exception:
                        pass

            # Deduplicate and format upcoming dates
            if upcoming_date_objs:
                unique_upcoming_dates = sorted(set(upcoming_date_objs))
                for d in unique_upcoming_dates:
                    day_name = d.strftime('%a')
                    date_str = d.strftime('%-m/%-d')  # No leading zeros
                    upcoming_dates.append(f"{day_name} {date_str}")

            # Format detail string with dates
            if upcoming_dates:
                dates_str = ", ".join(upcoming_dates)
                detail_text = f"{recurrence_desc} • Next: {dates_str}"
            else:
                detail_text = f"{recurrence_desc} • {pattern['instance_count']} upcoming"

            consolidated_item = {
                **first_item,  # Use first instance as base
                'is_recurring': True,
                'recurrence_pattern': pattern['type'],
                'recurrence_description': recurrence_desc,
                'recurrence_time': pattern['time'],
                'recurrence_days': pattern['days'],
                'next_occurrence': pattern['next_occurrence'],
                'instance_count': pattern['instance_count'],
                'all_instances': pattern['instances'],  # Keep all for deletion tracking
                'upcoming_dates': upcoming_dates,  # Human-readable date list
                # Update both title and detail to show recurrence clearly
                'title': f"{original_title} - {recurrence_desc}",
                'detail': detail_text
            }

            logger.info(
                f"[Recurring] ✅ Consolidated '{first_item.get('title')}': "
                f"{pattern['instance_count']} instances → {recurrence_desc}"
            )

            consolidated.append(consolidated_item)
        else:
            # No pattern detected, keep all items separate
            logger.info(
                f"[Recurring] ❌ No pattern for '{title}': "
                f"{len(group_items)} items at different times (keeping separate)"
            )
            consolidated.extend(group_items)

    return consolidated


def filter_completed_items(items: list, user_id: str, db: Session) -> list:
    if not items:
        return []
    completed = db.query(CompletedBriefItem).filter(
        CompletedBriefItem.user_id == user_id
    ).all()
    completed_signatures = {c.item_signature for c in completed}
    filtered = []
    for item in items:
        sig = generate_item_signature(item)
        if sig not in completed_signatures:
            filtered.append(item)
    return filtered


def filter_timeline_by_signatures(timeline_data, completed_signatures):
    if not completed_signatures:
        return timeline_data
    if isinstance(timeline_data, dict):
        filtered = {}
        for timeframe, priorities in timeline_data.items():
            if not isinstance(priorities, dict):
                filtered[timeframe] = priorities
                continue
            filtered[timeframe] = {}
            for priority, items in priorities.items():
                if isinstance(items, list):
                    filtered[timeframe][priority] = [
                        item for item in items
                        if item.get("signature") not in completed_signatures
                    ]
                else:
                    filtered[timeframe][priority] = items
        return filtered
    if isinstance(timeline_data, list):
        return [
            item for item in timeline_data
            if item.get("signature") not in completed_signatures
        ]
    return timeline_data


def count_timeline_items(timeline: dict) -> int:
    if not isinstance(timeline, dict):
        return 0
    total = 0
    for sections in timeline.values():
        if not isinstance(sections, dict):
            continue
        for items in sections.values():
            if isinstance(items, list):
                total += len(items)
    return total


def _filter_canon_with_completed(canon: UserCanonicalPlan, completed_signatures: set) -> dict:
    timeline = filter_timeline_by_signatures(canon.approved_timeline or {}, completed_signatures)
    priorities = filter_timeline_by_signatures(canon.active_priorities or [], completed_signatures)
    recs = [
        rec for rec in (canon.pending_recommendations or [])
        if rec.get("signature") not in completed_signatures
    ]
    return {
        "timeline": timeline,
        "priorities": priorities,
        "recommendations": recs,
        "last_ai_sync": canon.last_ai_sync.isoformat() if canon.last_ai_sync else None,
        "last_user_modification": canon.last_user_modification.isoformat() if canon.last_user_modification else None,
    }


def prune_plan_item(plan: UserCanonicalPlan, signature: str):
    if not plan:
        return False
    sig_set = {signature}
    removed = False
    priorities_removed = False
    timeline = plan.approved_timeline or {}
    for tf, sections in timeline.items():
        if not isinstance(sections, dict):
            continue
        for pri, items in sections.items():
            if not isinstance(items, list):
                continue
            new_items = [it for it in items if (it.get("signature") or generate_item_signature(it)) not in sig_set]
            if len(new_items) != len(items):
                timeline[tf][pri] = new_items
                removed = True
    if removed:
        plan.approved_timeline = timeline
        flag_modified(plan, "approved_timeline")

    priorities = plan.active_priorities or []
    new_priorities = []
    for it in priorities:
        sig = it.get("signature") or generate_item_signature(it)
        if sig in sig_set:
            priorities_removed = True
            continue
        new_priorities.append(it)
    if priorities_removed:
        plan.active_priorities = new_priorities
        flag_modified(plan, "active_priorities")

    recs = plan.pending_recommendations or []
    new_recs = [rec for rec in recs if rec.get("signature") not in sig_set]
    if len(new_recs) != len(recs):
        plan.pending_recommendations = new_recs
        flag_modified(plan, "pending_recommendations")

    return removed or priorities_removed or (len(new_recs) != len(recs))


def hard_remove_signature_from_canon(plan: UserCanonicalPlan, signatures):
    sig_set = set(signatures)
    timeline = plan.approved_timeline or {}
    for tf, sections in timeline.items():
        if not isinstance(sections, dict):
            continue
        for pri, items in sections.items():
            if isinstance(items, list):
                timeline[tf][pri] = [it for it in items if (it.get("signature") or "") not in sig_set]
    plan.approved_timeline = timeline
    flag_modified(plan, "approved_timeline")

    priorities = plan.active_priorities or []
    plan.active_priorities = [
        it for it in priorities if (it.get("signature") or "") not in sig_set
    ]
    flag_modified(plan, "active_priorities")

    recs = plan.pending_recommendations or []
    plan.pending_recommendations = [
        rec for rec in recs if (rec.get("signature") or "") not in sig_set
    ]
    flag_modified(plan, "pending_recommendations")
    return True


def get_or_create_canonical_plan(user_id: str, db: Session):
    default_timeline = {
        "1d": {"critical": [], "high": [], "normal": []},
        "7d": {"milestones": [], "goals": []},
        "28d": {"objectives": [], "projects": []},
    }

    plan = (
        db.query(UserCanonicalPlan)
        .filter(UserCanonicalPlan.user_id == user_id)
        .first()
    )

    if not plan:
        approved_timeline = default_timeline
        active_priorities = []
        now_ts = datetime.now(timezone.utc)

        try:
            user = db.query(UserORM).filter(UserORM.id == user_id).first()
            from app.services.gmail import fetch_unread_emails
            from app.services.calendar import fetch_upcoming_events

            if user:
                emails = fetch_unread_emails(user, db)
                events = fetch_upcoming_events(user, db)
                from main import _generate_personal_brief_with_ai
                ai_result = _generate_personal_brief_with_ai(user, emails, events, db)
                approved_timeline = ai_result.get("timeline", default_timeline)
                active_priorities = ai_result.get("priorities", [])
        except Exception as e:
            logger.warning(f"[Canon] Failed to auto-populate canonical plan: {e}")
            approved_timeline = default_timeline
            active_priorities = []

        plan = UserCanonicalPlan(
            id=str(uuid.uuid4()),
            user_id=user_id,
            approved_timeline=approved_timeline,
            active_priorities=active_priorities,
            pending_recommendations=[],
            dismissed_items=[],
            last_ai_sync=now_ts,
            last_user_modification=now_ts,
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        logger.info(f"[Canon] Created canonical plan for user {user_id}")

    return plan


def should_regenerate_recommendations(canonical_plan: UserCanonicalPlan) -> bool:
    if not canonical_plan.last_ai_sync:
        return True
    age = datetime.now(timezone.utc) - canonical_plan.last_ai_sync
    return age.total_seconds() > 3600


def generate_recommendations(user, emails, events, canonical_plan, db, completed_signatures=None, is_manual_refresh=False):
    events = events or []
    emails = emails or []

    logger.warning("=" * 80)
    logger.warning(f"🔥 [Timeline Input] STARTING for USER: {getattr(user, 'email', user.id)}")
    logger.warning(f"[Timeline Input] TOTAL CALENDAR EVENTS: {len(events)}")
    logger.warning(f"[Timeline Input] TOTAL EMAILS: {len(emails)}")
    logger.warning("=" * 80)

    logger.warning("[Timeline Input] === ALL CALENDAR EVENTS ===")
    for i, event in enumerate(events, 1):
        title = event.get('title') or event.get('summary') or 'NO TITLE'
        logger.warning(f"  {i}. {title}")
        if i <= 5:  # Only show details for first 5 to reduce noise
            logger.warning(
                f"     Time: {event.get('start') or event.get('start_time') or 'NONE'} "
                f"to {event.get('end') or event.get('end_time') or 'NONE'}"
            )
            logger.warning(f"     Source ID: {event.get('source_id') or event.get('id') or 'NONE'}")

    if len(events) > 5:
        logger.warning(f"  ... and {len(events) - 5} more events")

    logger.warning(f"\n[Timeline Input] === EMAIL SAMPLE (first 5 of {len(emails)}) ===")
    for i, email in enumerate(emails[:5], 1):
        logger.warning(f"  {i}. Subject: {email.get('subject') or email.get('title') or 'NO SUBJECT'}")
        logger.warning(f"     From: {email.get('from') or email.get('sender') or 'UNKNOWN'}")

    if len(emails) > 5:
        logger.warning(f"  ... and {len(emails) - 5} more emails")

    logger.warning("=" * 80)

    # === DIAGNOSTIC HELPER FUNCTION ===
    def count_items(items, label):
        """Track item counts at each pipeline stage"""
        total = len(items)
        calendar = sum(1 for i in items if i.get('source_type') == 'calendar')
        email = sum(1 for i in items if i.get('source_type') == 'email')
        actionable = sum(1 for i in items if 'actionable time' in str(i.get('title', '')).lower())

        logger.warning("=" * 80)
        logger.warning(f"🔍 [{label}] ITEM COUNTS:")
        logger.warning(f"[{label}] Total: {total}")
        logger.warning(f"[{label}]   - Calendar: {calendar}")
        logger.warning(f"[{label}]   - Email: {email}")
        logger.warning(f"[{label}] 🎯 'Actionable time': {actionable}")

        # Show all "Actionable time" items with source IDs
        if actionable > 0:
            logger.warning(f"[{label}] === ALL 'Actionable time' ITEMS ===")
            for i, item in enumerate(items, 1):
                if 'actionable time' in str(item.get('title', '')).lower():
                    source_id = item.get('source_id') or item.get('id') or 'NO_SOURCE_ID'
                    title = item.get('title') or item.get('summary') or 'NO TITLE'
                    logger.warning(f"[{label}]   {i}. {title}")
                    logger.warning(f"[{label}]      Source ID: {source_id}")

        logger.warning("=" * 80)
        return total

    approved_timeline = canonical_plan.approved_timeline or {
        "1d": {"critical": [], "high": [], "normal": []},
        "7d": {"milestones": [], "goals": []},
        "28d": {"objectives": [], "projects": []}
    }
    approved_priorities = canonical_plan.active_priorities or []
    dismissed_signatures = {
        generate_item_signature(item)
        for item in (canonical_plan.dismissed_items or [])
    }
    if completed_signatures is None:
        completed_signatures = {
            c.item_signature for c in db.query(CompletedBriefItem).filter(CompletedBriefItem.user_id == user.id).all()
        }
    else:
        completed_signatures = set(completed_signatures)
    existing_rec_signatures = {
        rec.get('signature')
        for rec in (canonical_plan.pending_recommendations or [])
        if rec.get('signature')
    }

    from main import _generate_personal_brief_with_ai

    debug_logging = getattr(user, "email", None) == CANON_DEBUG_EMAIL

    def log_info(msg: str):
        if debug_logging:
            logger.info(msg)

    def log_warning(msg: str):
        if debug_logging:
            logger.warning(msg)

    log_info("════════════════════════════════════════════════════════════════")
    log_info(f"[Canon] 🎯 GENERATING TIMELINE for {user.email}")
    log_info("════════════════════════════════════════════════════════════════")

    # Timezone-aware event processing
    user_timezone = get_user_timezone(user, db)
    log_info(f"[Canon] 📍 User timezone: {user_timezone}")
    user_tz = pytz.timezone(user_timezone)
    now_user_tz = datetime.now(pytz.UTC).astimezone(user_tz)
    log_info(f"[Canon] 🕐 Current time (user TZ): {now_user_tz.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    raw_events = events or []
    log_info(f"[Canon] 📥 Fetched {len(raw_events)} raw events")
    if raw_events and debug_logging:
        log_info("[Canon] 📋 Sample raw events:")
        for i, ev in enumerate(raw_events[:3]):
            log_info(
                f"[Canon]   - Event {i+1}: '{ev.get('title') or ev.get('summary')}' at "
                f"{ev.get('start_time') or ev.get('start')}"
            )

    # CRITICAL: Add source_type to emails (they don't come with it from Gmail fetch)
    raw_emails = emails or []

    # Track email filtering for observability
    email_drop_reasons = {}
    email_drop_samples = []

    for email in raw_emails:
        if 'source_type' not in email:
            email['source_type'] = 'email'
        # Also ensure each email has a source_id for deduplication
        if 'source_id' not in email and 'id' in email:
            email['source_id'] = email['id']

    logger.warning(f"[Pre-Stage-0] 📧 Processed {len(raw_emails)} emails with source_type")
    logger.warning(f"[Pre-Stage-0] 📅 Processed {len(raw_events)} calendar events")

    cache_key = _cache_key(user.email)

    # === STAGE 0: Initial (Raw Events + Emails) ===
    stage0_items = raw_emails + raw_events
    stage0_count = count_items(stage0_items, "STAGE 0: Initial")

    # Cache stage 0 data for admin debug with email observability
    stage0_items_sanitized = [_sanitize_item(it) for it in stage0_items[:100]]

    cache_stage_data(cache_key, "stage_0", {
        "total_items": stage0_count,
        "calendar_events": len(raw_events),
        "emails": len(raw_emails),
        "email_stage0_counts": {
            "fetched": len(raw_emails),
            "valid": len(raw_emails),  # Will be updated after validation
            "dropped": 0  # Will be updated after filtering
        },
        "stage_items": stage0_items_sanitized,
    })
    TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_0_initial"] = stage0_items_sanitized
    TIMELINE_DEBUG_CACHE[cache_key]["email_stage_0"] = {
        "total_emails_loaded": len(raw_emails),
        "filtered_out_count": 0,
        "filter_reasons_breakdown": {},
        "sample_ids": [],
    }
    _record_stage(cache_key, "stage_0_initial", "Initial items", stage0_count, stage0_count)

    # Step 1: Remove exact duplicates by source_id (MUST BE FIRST)
    events = deduplicate_by_source_id(raw_events)
    log_info(f"[Canon] 🔑 After source_id dedup: {len(events)} events")

    # === STAGE 1: After source_id dedup ===
    stage1_items = raw_emails + events
    stage1_count = count_items(stage1_items, "STAGE 1: After source_id dedup")
    logger.warning(f"⚠️ LOSS REPORT: Stage 0 → Stage 1: Lost {stage0_count - stage1_count} items")
    TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_1_dedup_ids"] = [_sanitize_item(it) for it in stage1_items[:100]]
    _record_stage(cache_key, "stage_1_dedup_ids", "After source_id dedup", stage0_count, stage1_count)

    # Step 2: Remove similar duplicate events (e.g., 3x "Supabase Security Issue")
    events = deduplicate_similar_events(events, similarity_threshold=0.7)

    # === STAGE 2: After similar events dedup ===
    stage2_items = raw_emails + events
    stage2_count = count_items(stage2_items, "STAGE 2: After similar dedup")
    logger.warning(f"⚠️ LOSS REPORT: Stage 1 → Stage 2: Lost {stage1_count - stage2_count} items")
    TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_2_semantic"] = [_sanitize_item(it) for it in stage2_items[:100]]
    _record_stage(cache_key, "stage_2_semantic", "After similar dedup", stage1_count, stage2_count)

    # Step 3: Remove "Prepare for X" when main event exists
    events = deduplicate_prep_events(events)

    # === STAGE 3: After prep events dedup ===
    stage3_items = raw_emails + events
    stage3_count = count_items(stage3_items, "STAGE 3: After prep dedup")
    logger.warning(f"⚠️ LOSS REPORT: Stage 2 → Stage 3: Lost {stage2_count - stage3_count} items")
    TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_3_prep"] = [_sanitize_item(it) for it in stage3_items[:100]]
    _record_stage(cache_key, "stage_3_prep", "After prep dedup", stage2_count, stage3_count)

    # Step 4: Remove semantically similar events (e.g., "Trade with Chase" vs "Trading with Chase")
    events = deduplicate_by_semantics(events, threshold=0.90)
    log_info(f"[Canon] 🔄 After all deduplication: {len(events)} events (removed {len(raw_events) - len(events)} total)")

    # === STAGE 4: After semantic dedup ===
    stage4_items = raw_emails + events
    stage4_count = count_items(stage4_items, "STAGE 4: After semantic dedup")
    logger.warning(f"⚠️ LOSS REPORT: Stage 3 → Stage 4: Lost {stage3_count - stage4_count} items")
    TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_4_semantic"] = [_sanitize_item(it) for it in stage4_items[:100]]
    _record_stage(cache_key, "stage_4_semantic", "After semantic dedup", stage3_count, stage4_count)

    processed_events = []
    skipped_past_count = 0

    for ev in events or []:
        event_time = ev.get("start_time") or ev.get("start") or ev.get("deadline")
        if not event_time:
            log_warning(f"[Canon] ⚠️  Event '{ev.get('title') or ev.get('summary')}' has NO start_time - skipping")
            continue
        deadline_info = calculate_event_deadline(event_time, user_timezone)

        # Parse event datetime for same-day check
        try:
            event_dt = parse_datetime(event_time).astimezone(user_tz)
            event_date = event_dt.date()
        except Exception as e:
            event_dt = None
            event_date = None
            log_warning(f"[Canon] ⚠️  Could not parse event time for '{ev.get('title') or ev.get('summary')}': {e}")

        log_info(
            f"[Canon] 📅 Event: '{ev.get('title') or ev.get('summary')}' | "
            f"time={event_time} | hours_until={deadline_info['hours_until']:.1f} | "
            f"is_past={deadline_info['is_past']} | deadline_text={deadline_info['deadline_text']}"
        )

        # Allow same-day events even if time has passed
        if deadline_info["is_past"]:
            if event_date and event_date == now_user_tz.date():
                log_info(f"[Canon] ⏩ KEEPING past-but-today event: '{ev.get('title') or ev.get('summary')}'")
            else:
                skipped_past_count += 1
                log_info(f"[Canon] ⏭️  SKIPPING past event: '{ev.get('title') or ev.get('summary')}'")
                continue

        # Preserve raw timestamp for recurrence detection before overwriting with human-readable text
        ev["deadline_raw"] = event_time
        ev["deadline"] = deadline_info["deadline_text"]
        ev["hours_until"] = deadline_info["hours_until"]
        processed_events.append(ev)
        log_info(f"[Canon] ✅ KEEPING future event: '{ev.get('title') or ev.get('summary')}'")

    log_info("════════════════════════════════════════════════════════════════")
    log_info(
        f"[Canon] 📊 Event processing summary: "
        f"raw={len(raw_events)}, deduped={len(events)}, kept={len(processed_events)}, "
        f"skipped_past={skipped_past_count}"
    )
    logger.warning(f"[Time Filter] Input: {len(events)} events | Removed past: {skipped_past_count} | Kept: {len(processed_events)}")
    log_info("════════════════════════════════════════════════════════════════")

    # === STAGE 5: After time-based filtering (past events removed) ===
    stage5_items = raw_emails + processed_events
    stage5_count = count_items(stage5_items, "STAGE 5: After time filter")
    logger.warning(f"⚠️ LOSS REPORT: Stage 4 → Stage 5: Lost {stage4_count - stage5_count} items (past events)")
    TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_5_time_filter"] = [_sanitize_item(it) for it in stage5_items[:100]]
    _record_stage(cache_key, "stage_5_time_filter", "After time filter", stage4_count, stage5_count)

    # Step 4: Filter CALENDAR EVENTS by deletion patterns
    # CRITICAL FIX: Do NOT filter emails here - they don't have proper time fields yet
    # Only apply deletion pattern filtering to calendar events
    logger.warning(f"[Deletion Filter] 🔍 Filtering ONLY calendar events (not emails)")
    filtered_events = filter_by_deletion_patterns(processed_events, user.id, db)

    # Emails pass through unfiltered (deletion patterns require time fields that emails don't have yet)
    filtered_emails = raw_emails
    logger.warning(f"[Email Passthrough] ✅ {len(filtered_emails)} emails passed through without deletion filtering")

    # Track email drops for observability
    emails_dropped_count = 0  # None dropped at this stage
    for email in raw_emails[:10]:  # Track first 10 as samples
        email_drop_samples.append({
            "id": email.get("id") or email.get("source_id"),
            "subject": email.get("subject", "")[:100],  # First 100 chars
            "reason": "none - passed through"
        })

    # === STAGE 6: After deletion pattern filter ===
    filtered_items = filtered_emails + filtered_events
    stage6_count = count_items(filtered_items, "STAGE 6: After deletion filter")
    logger.warning(f"⚠️ LOSS REPORT: Stage 5 → Stage 6: Lost {stage5_count - stage6_count} items (filtered by deletion patterns)")
    TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_6_deletion_filter"] = [_sanitize_item(it) for it in filtered_items[:100]]
    _record_stage(cache_key, "stage_6_deletion_filter", "After deletion filter", stage5_count, stage6_count)

    # Update email observability data
    email_drop_reasons["deletion_filter"] = 0  # No emails dropped by this filter
    cache_stage_data(cache_key, "email_filtering", {
        "emails_kept": len(filtered_emails),
        "emails_dropped_deletion_filter": 0,
        "drop_reasons": email_drop_reasons,
        "drop_samples": email_drop_samples[:10]
    })
    TIMELINE_DEBUG_CACHE[cache_key]["email_stage_0"] = {
        "total_emails_loaded": len(raw_emails),
        "filtered_out_count": 0,
        "filter_reasons_breakdown": email_drop_reasons,
        "sample_ids": [s.get("id") for s in email_drop_samples if s.get("id")] if isinstance(email_drop_samples, list) else [],
    }

    if debug_logging:
        items_removed = stage5_count - stage6_count
        if items_removed > 0:
            log_info(f"[Canon] 🎯 Smart filtering removed {items_removed} low-engagement calendar events")

    # === STAGE 6.5: Pre-AI recurring consolidation for calendar events ===
    logger.warning("=" * 80)
    logger.warning("🚨 [CRITICAL DEBUG] About to call pre-AI consolidation")
    logger.warning(f"🚨 Filtered events count: {len(filtered_events)}")
    logger.warning(f"🚨 Filtered events sample: {[e.get('title') for e in filtered_events[:5]]}")
    logger.warning("=" * 80)

    try:
        logger.warning(f"[Stage 6.5] 🔄 Running PRE-AI recurring consolidation")
        consolidated_events_pre_ai = consolidate_recurring_events(filtered_events)
        logger.warning(f"🚨 [CRITICAL DEBUG] Pre-AI consolidation COMPLETED")
        logger.warning(f"🚨 Output count: {len(consolidated_events_pre_ai)}")
        logger.warning(f"[Stage 6.5] ✅ Consolidation complete: {len(filtered_events)} → {len(consolidated_events_pre_ai)} events")

        # Cache recurring patterns for admin debug
        patterns_removed = len(filtered_events) - len(consolidated_events_pre_ai)
        cache_stage_data(cache_key, "stage_65_recurring", {
            "events_before": len(filtered_events),
            "events_after": len(consolidated_events_pre_ai),
            "patterns_consolidated": patterns_removed
        })
        TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_65_recurring"] = [_sanitize_item(it) for it in consolidated_events_pre_ai[:100]]
    except Exception as e:
        logger.error(f"🚨 [CRITICAL DEBUG] Pre-AI consolidation FAILED: {e}")
        logger.error(f"🚨 Exception: {traceback.format_exc()}")
        consolidated_events_pre_ai = filtered_events

    ai_input_items = filtered_emails + consolidated_events_pre_ai

    stage65_count = count_items(ai_input_items, "STAGE 6.5: After pre-AI recurring consolidation")
    logger.warning(f"⚠️ LOSS REPORT: Stage 6 → Stage 6.5: Lost {stage6_count - stage65_count} items (recurring consolidation)")
    _record_stage(cache_key, "stage_65_recurring", "Pre-AI recurring consolidation", stage6_count, stage65_count)

    # === STAGE FINAL: Items sent to AI ===
    logger.warning("=" * 80)
    logger.warning("🤖 [STAGE FINAL] === COMPLETE LIST SENT TO AI ===")
    logger.warning(f"[STAGE FINAL] Total items: {len(ai_input_items)}")
    logger.warning(f"[STAGE FINAL]   - Emails: {len(filtered_emails)}")
    logger.warning(f"[STAGE FINAL]   - Events: {len(consolidated_events_pre_ai)}")
    logger.warning("")
    logger.warning("[STAGE FINAL] ALL ITEMS BEING SENT TO AI:")
    for i, item in enumerate(ai_input_items, 1):
        title = item.get('title') or item.get('summary') or item.get('subject') or 'NO TITLE'
        source_type = item.get('source_type') or 'UNKNOWN'
        source_id = item.get('source_id') or item.get('id') or 'NO_SOURCE_ID'
        time_field = (
            item.get('deadline') or
            item.get('start') or
            item.get('start_time') or
            item.get('received_at') or
            'NO_TIME'
        )
        logger.warning(f"  {i}. [{source_type}] {title}")
        logger.warning(f"     Source ID: {source_id}")
        logger.warning(f"     Time: {time_field}")
    logger.warning("=" * 80)
    logger.warning(f"⚠️ FINAL LOSS REPORT: Stage 0 → Final: Lost {stage0_count - stage65_count} total items")
    logger.warning("=" * 80)

    # Cache AI input stats for admin debug
    cache_ai_stats(cache_key, len(ai_input_items), 0, stage0_count - stage65_count)
    cache_stage_data(cache_key, "stage_final_pre_ai", {
        "total_items": len(ai_input_items),
        "emails": len(filtered_emails),
        "calendar_events": len(consolidated_events_pre_ai),
        "items_lost_total": stage0_count - stage65_count
    })
    TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_final_pre_ai"] = [_sanitize_item(it) for it in ai_input_items[:100]]
    _record_stage(cache_key, "stage_final_pre_ai", "Pre-AI payload", stage6_count, len(ai_input_items))

    ai_result = _generate_personal_brief_with_ai(user, filtered_emails, consolidated_events_pre_ai, db)

    # Sanitize AI response deadlines (common format fixes)
    def sanitize_deadline(deadline_str):
        if not isinstance(deadline_str, str):
            return deadline_str
        # Fix lowercase 't'
        deadline_str = re.sub(r'(\d{4}-\d{2}-\d{2})t(\d{2}:\d{2}:\d{2})', r'\1T\2', deadline_str, flags=re.IGNORECASE)
        # Add timezone if missing
        if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$', deadline_str):
            deadline_str += '-08:00'
        return deadline_str

    ai_timeline_raw = ai_result.get('timeline', {})
    for tf in ['1d', '7d', '28d']:
        tf_data = ai_timeline_raw.get(tf, {}) if isinstance(ai_timeline_raw, dict) else {}
        for section in ['urgent', 'normal']:
            items = tf_data.get(section, []) if isinstance(tf_data, dict) else []
            for item in items:
                if 'deadline' in item:
                    item['deadline'] = sanitize_deadline(item.get('deadline'))
                if 'deadline_raw' in item:
                    item['deadline_raw'] = sanitize_deadline(item.get('deadline_raw'))

    # VALIDATE AND FIX AI CATEGORIZATION MISTAKES
    # The AI sometimes puts tomorrow's events in 28d instead of 7d
    ai_timeline = ai_result.get('timeline', {})
    validated_timeline = validate_and_fix_categorization(ai_timeline, user_timezone)
    ai_result['timeline'] = validated_timeline

    # Stabilize AI output with small minimums/caps and backfill
    min_counts = {'1d': 2, '7d': 3, '28d': 3}
    max_counts = {'1d': 5, '7d': 7, '28d': 7}

    # Use Stage 6 items as backfill pool
    backfill_pool = filtered_items
    stabilized_timeline = stabilize_timeline_output(
        validated_timeline,
        backfill_pool,
        user_tz,
        min_counts,
        max_counts,
        now_user_tz.date(),
        now_user_tz.date() + timedelta(days=7),
        now_user_tz.date() + timedelta(days=28),
    )
    ai_result['timeline'] = stabilized_timeline

    # Cache AI output stats for admin debug
    ai_items_returned = count_timeline_items(stabilized_timeline)
    cache_ai_stats(cache_key, len(ai_input_items), ai_items_returned, stage0_count - ai_items_returned)
    cache_stage_data(cache_key, "stage_post_ai", {
        "total_items": ai_items_returned,
        "1d_items": len(stabilized_timeline.get("1d", {}).get("urgent", [])) + len(stabilized_timeline.get("1d", {}).get("normal", [])),
        "7d_items": len(stabilized_timeline.get("7d", {}).get("urgent", [])) + len(stabilized_timeline.get("7d", {}).get("normal", [])),
        "28d_items": len(stabilized_timeline.get("28d", {}).get("urgent", [])) + len(stabilized_timeline.get("28d", {}).get("normal", []))
    })
    sanitized_post_ai = []
    for tf in ["1d", "7d", "28d"]:
        for pr in ["urgent", "normal"]:
            sanitized_post_ai.extend([_sanitize_item(it) for it in stabilized_timeline.get(tf, {}).get(pr, [])][:50])
    TIMELINE_DEBUG_CACHE[cache_key]["stage_items"]["stage_post_ai"] = sanitized_post_ai[:100]
    _record_stage(cache_key, "stage_post_ai", "Post-AI stabilized", len(ai_input_items), ai_items_returned)
    TIMELINE_DEBUG_CACHE[cache_key]["pipeline_totals"] = {
        "input_total": stage0_count,
        "final_total": ai_items_returned,
    }
    TIMELINE_DEBUG_CACHE[cache_key]["last_refresh_ts"] = datetime.now(timezone.utc).isoformat()

    # === FIX #2: Restore deadline_raw fields that AI stripped ===
    # Create a lookup of original events by source_id
    original_events_map = {}
    for item in ai_input_items:  # ai_input_items = what was sent to AI
        source_id = item.get('source_id')
        if source_id:
            original_events_map[source_id] = item

    # Restore deadline_raw to AI-returned events
    restored_count = 0
    for timeframe in ['1d', '7d', '28d']:
        for priority in ['urgent', 'normal']:
            items = stabilized_timeline.get(timeframe, {}).get(priority, [])
            for item in items:
                source_id = item.get('source_id')
                if source_id and source_id in original_events_map:
                    original = original_events_map[source_id]
                    # Restore raw timestamp fields
                    if 'deadline_raw' in original and 'deadline_raw' not in item:
                        item['deadline_raw'] = original['deadline_raw']
                        restored_count += 1
                    if 'start' not in item and 'start' in original:
                        item['start'] = original['start']
                    if 'start_time' not in item and 'start_time' in original:
                        item['start_time'] = original['start_time']

    logger.warning(f"[AI Response] ✅ Restored deadline_raw to {restored_count} events")

    # Cache validation fix count for admin debug
    if restored_count > 0:
        cache_validation_fix(user.email, restored_count)

    # === FIX #3: Validate and fix AI-returned deadline formats ===
    def is_iso_datetime(value):
        """Check if string looks like ISO datetime"""
        if not isinstance(value, str):
            return False
        # Matches patterns like: 2026-01-02T06:30:00-08:00
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value))

    def format_relative_time(iso_string):
        """Convert ISO string to human-readable relative time"""
        try:
            dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            diff = dt - now

            hours = diff.total_seconds() / 3600

            if hours < -1:
                return f"{abs(int(hours))} hours ago"
            elif hours < 0:
                return "Just passed"
            elif hours < 1:
                return "Due now"
            elif hours < 24:
                return f"Due in {int(hours)} hours"
            else:
                days = int(hours / 24)
                return f"Due in {days} day{'s' if days != 1 else ''}"
        except:
            return iso_string  # Return original if parsing fails

    # Validate and fix deadlines in AI timeline
    fixed_count = 0
    for timeframe in ['1d', '7d', '28d']:
        for priority in ['urgent', 'normal']:
            items = stabilized_timeline.get(timeframe, {}).get(priority, [])
            for item in items:
                deadline = item.get('deadline')

                # If deadline is an ISO string, convert to human-readable
                if deadline and is_iso_datetime(deadline):
                    logger.warning(
                        f"[AI Response] ⚠️  Fixing invalid deadline format for '{item.get('title')}': {deadline}"
                    )
                    item['deadline'] = format_relative_time(deadline)
                    fixed_count += 1

                    # Ensure deadline_raw exists for future processing
                    if 'deadline_raw' not in item:
                        item['deadline_raw'] = deadline

    if fixed_count > 0:
        logger.warning(f"[AI Response] ⚠️  Fixed {fixed_count} invalid deadline format(s)")
    else:
        logger.warning(f"[AI Response] ✅ All deadline formats valid")

    recommendations = []
    for timeframe in ['1d', '7d', '28d']:
        ai_timeframe = stabilized_timeline.get(timeframe, {})
        approved_timeframe = approved_timeline.get(timeframe, {})

        for section_key, section_items in ai_timeframe.items():
            if not isinstance(section_items, list):
                continue
            approved_section = approved_timeframe.get(section_key, [])

            for item in section_items:
                sig = item.get("signature") or generate_item_signature(item)
                is_approved = any(
                    (approved.get("signature") or generate_item_signature(approved)) == sig
                    for approved in approved_section
                )
                is_dismissed = sig in dismissed_signatures
                if sig in completed_signatures:
                    continue
                already_recommended = sig in existing_rec_signatures

                if not is_approved and not is_dismissed and not already_recommended:
                    recommendations.append({
                        "item": item,
                        "reason": f"New {section_key} item detected",
                        "timeframe": timeframe,
                        "section": section_key,
                        "type": "timeline_addition",
                        "signature": sig
                    })

    logger.info(f"[Recs] Generated {len(recommendations)} new rec candidates (after skips).")

    canonical_plan.approved_timeline = approved_timeline
    flag_modified(canonical_plan, "approved_timeline")
    canonical_plan.pending_recommendations = []
    flag_modified(canonical_plan, "pending_recommendations")

    added_to_timeline = 0
    for rec in recommendations:
        timeframe = rec.get("timeframe") or "1d"
        section = rec.get("section") or "high"
        item = rec.get("item") or {}
        sig = rec.get("signature") or generate_item_signature(item)
        rec["signature"] = sig
        if sig and not item.get("signature"):
            item["signature"] = sig

        approved_timeline.setdefault(timeframe, {})
        approved_timeline[timeframe].setdefault(section, [])
        existing_sigs = {
            (it.get("signature") or generate_item_signature(it))
            for it in approved_timeline[timeframe][section]
            if isinstance(it, dict)
        }
        if sig in existing_sigs:
            continue

        approved_timeline[timeframe][section].append(item)
        added_to_timeline += 1
    logger.info(f"[Auto-Timeline] Added {added_to_timeline} tasks directly to timeline")

    # NOTE: Consolidation already happened BEFORE AI (Stage 6.5)
    # No need to consolidate again here - AI already received consolidated events
    logger.warning("[Timeline] ℹ️  Skipping post-AI consolidation (already done pre-AI)")

    # Update the canonical plan with timeline

    logger.warning("=" * 80)
    logger.warning("✅ [Timeline Final] === FINAL TIMELINE BEING SAVED ===")
    for timeframe in ['1d', '7d', '28d']:
        for priority in ['urgent', 'normal']:
            items = approved_timeline.get(timeframe, {}).get(priority, [])
            if len(items) > 0:  # Only log non-empty sections
                logger.warning(f"[Timeline Final] {timeframe}/{priority}: {len(items)} items")
                for i, item in enumerate(items[:3], 1):
                    logger.warning(f"  {i}. {item.get('title', 'NO TITLE')}")
                if len(items) > 3:
                    logger.warning(f"  ... and {len(items) - 3} more")

    total_final = sum(
        len(approved_timeline.get(tf, {}).get(pr, []))
        for tf in ['1d', '7d', '28d']
        for pr in ['urgent', 'normal']
    )
    logger.warning(f"[Timeline Final] ✅ TOTAL items saved to DB: {total_final}")
    logger.warning("=" * 80)

    canonical_plan.approved_timeline = approved_timeline
    flag_modified(canonical_plan, "approved_timeline")

    return {"recommendations": recommendations, "added": added_to_timeline}


def _normalize_dt(value: Optional[datetime]) -> Optional[datetime]:
    if value and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _get_refresh_interval_minutes(user: UserORM, default_interval: int, allowed: set[int]) -> int:
    prefs = user.preferences or {}
    interval = prefs.get("canon_refresh_interval_minutes", default_interval)
    try:
        interval_int = int(interval)
    except Exception:
        return default_interval
    if interval_int not in allowed:
        return default_interval
    return interval_int
