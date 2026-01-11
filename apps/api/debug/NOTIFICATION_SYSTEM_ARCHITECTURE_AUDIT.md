# 🔍 Backend Architecture Audit: Notification & Knowledge Graph System

**Date**: 2026-01-01
**Purpose**: Comprehensive audit before building flexible, multi-source notification system
**Status**: ✅ COMPLETE

---

## Executive Summary

### ✅ What We Have
- **Notifications table** with basic CRUD endpoints
- **user_actions table** with vector embeddings (pgvector 0.8.1)
- **APScheduler background job system** (currently running every 1 minute)
- **RAG implementation** using pgvector + OpenAI embeddings
- **Activity Manager** with semantic similarity detection
- **Team/Room hierarchy** with organizations and memberships

### ⚠️ What's Missing
- **No VSCode integration endpoints** (need to create)
- **No conflict detection logic** (need to implement)
- **No multi-source notification aggregation** (need to design)
- **Limited notification schema** (missing severity, embeddings, related entities)

### 🎯 Extensibility Score: **7/10**
- Strong foundation with pgvector and proper data models
- Good background job infrastructure
- Needs refactoring for multi-source flexibility

---

## 1. Database Schema Analysis

### ✅ Existing Tables

#### `notifications` Table
```sql
CREATE TABLE notifications (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES users(id),
    type VARCHAR,                    -- Current: 'task', etc.
    title VARCHAR NOT NULL,
    message TEXT,
    task_id VARCHAR REFERENCES tasks(id),
    created_at TIMESTAMP,
    is_read BOOLEAN DEFAULT FALSE,
    data JSONB DEFAULT '{}'          -- Flexible storage (good!)
);
```

**Indexes**:
- `ix_notifications_id` (btree)
- `ix_notifications_user_id` (btree)

**✅ Strengths**:
- Has `data` JSONB column for flexibility
- Proper foreign keys and indexes
- Boolean read status

**⚠️ Limitations**:
- No `source_type` or `source_id` columns
- No `severity` field (normal/urgent)
- No embeddings for RAG queries
- No `read_at` timestamp
- No `room_id` for team context
- No related users/files arrays

---

#### `user_actions` Table ⭐ (Best for Activity Tracking)
```sql
CREATE TABLE user_actions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR NOT NULL REFERENCES users(id),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Source tracking
    tool VARCHAR(50) NOT NULL,              -- 'chat', 'gmail', 'calendar', 'vscode'
    action_type VARCHAR(100) NOT NULL,      -- 'chat_message', 'code_edit', etc.
    action_data JSONB NOT NULL DEFAULT '{}',-- Flexible data (files, changes, etc.)

    -- Context
    task_id VARCHAR REFERENCES tasks(id),
    session_id VARCHAR(100),
    room_id VARCHAR REFERENCES rooms(id),

    -- AI-generated metadata
    activity_summary TEXT,                  -- AI-generated summary
    activity_embedding VECTOR(1536),        -- OpenAI text-embedding-3-small
    similarity_to_status FLOAT,
    similarity_to_previous FLOAT,
    is_status_change BOOLEAN DEFAULT FALSE
);
```

**Indexes**:
- `user_actions_pkey` (PRIMARY KEY)
- `idx_user_actions_embedding` (**ivfflat** for fast vector search!)
- `idx_user_actions_room_id`, `idx_user_actions_user_id`, `idx_user_actions_timestamp`
- `idx_user_actions_status_change` (WHERE is_status_change = true)

**✅ Perfect for Multi-Source Activity!**:
- `tool` column supports any source (`'vscode'`, `'github'`, `'drive'`)
- `action_data` JSONB can store file paths, code changes, commits, etc.
- Vector embeddings already implemented
- Similarity detection for deduplication

---

#### `users`, `rooms`, `organizations` Tables
```sql
CREATE TABLE users (
    id VARCHAR PRIMARY KEY,
    email VARCHAR UNIQUE NOT NULL,
    name VARCHAR NOT NULL,
    role VARCHAR,
    preferences JSON,
    permissions JSON NOT NULL DEFAULT '{}',
    org_id VARCHAR REFERENCES organizations(id),
    created_at TIMESTAMP
);

CREATE TABLE rooms (
    id VARCHAR PRIMARY KEY,
    org_id VARCHAR NOT NULL REFERENCES organizations(id),
    name VARCHAR NOT NULL,              -- e.g., "Team", "Project X"
    project_summary TEXT,
    memory_summary TEXT,
    created_at TIMESTAMP
);

CREATE TABLE room_members (
    room_id VARCHAR REFERENCES rooms(id),
    user_id VARCHAR REFERENCES users(id),
    -- Additional membership fields
);
```

**✅ Team Hierarchy Exists**:
- Organizations → Rooms → Users
- Good for manager dashboards

---

### 🔧 Recommended Schema Changes

#### Option 1: Extend `notifications` Table (Minimal Changes)
```sql
ALTER TABLE notifications
    ADD COLUMN source_type VARCHAR,          -- 'activity', 'vscode', 'github', etc.
    ADD COLUMN source_id VARCHAR,            -- ID in source system
    ADD COLUMN severity VARCHAR DEFAULT 'normal',  -- 'normal', 'urgent'
    ADD COLUMN context_embedding VECTOR(1536),     -- For RAG queries
    ADD COLUMN related_users VARCHAR[],            -- UUIDs of involved users
    ADD COLUMN related_files TEXT[],               -- File paths for conflicts
    ADD COLUMN room_id VARCHAR REFERENCES rooms(id),
    ADD COLUMN read_at TIMESTAMP;

CREATE INDEX idx_notifications_source ON notifications(source_type, source_id);
CREATE INDEX idx_notifications_severity ON notifications(severity) WHERE severity = 'urgent';
CREATE INDEX idx_notifications_embedding ON notifications USING ivfflat (context_embedding vector_cosine_ops);
```

#### Option 2: Use `user_actions` as Primary Source (Recommended)
- **Keep `user_actions` for all activity tracking** (already perfect)
- **Use `notifications` for user-facing alerts only**
- **Generate notifications FROM user_actions** via background job

**Benefits**:
- Single source of truth for activity
- No schema duplication
- Leverage existing embeddings
- Easier conflict detection (compare activities)

---

## 2. Background Job System ✅

### APScheduler Already Running!

**File**: `app/workers/canon_worker.py`

**Current Setup**:
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

# Runs every 1 minute (configurable)
CANON_WORKER_CHECK_INTERVAL_MINUTES = 1

scheduler.add_job(
    refresh_stale_canons,
    "interval",
    minutes=CANON_WORKER_CHECK_INTERVAL_MINUTES,
    id="canon_refresh_worker",
    replace_existing=True,
)
```

**✅ Ready for Notifications Job!**

### How to Add Notification Detection Job

```python
# In app/workers/notification_worker.py (NEW FILE)

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger("notification_worker")
scheduler = AsyncIOScheduler()  # Reuse or create new

NOTIFICATION_CHECK_INTERVAL_MINUTES = 15  # Configurable via ENV

async def detect_and_create_notifications():
    """
    Scan user_actions for:
    1. File conflicts (overlapping work)
    2. Status changes (significant updates)
    3. Collaboration opportunities
    """
    db = SessionLocal()
    try:
        # 1. Find overlapping file edits
        conflicts = detect_file_conflicts(db)
        for conflict in conflicts:
            create_urgent_notification(db, conflict)

        # 2. Find significant activities
        activities = detect_significant_activities(db)
        for activity in activities:
            create_normal_notification(db, activity)

        db.commit()
        logger.info(f"✅ Created {len(conflicts)} urgent + {len(activities)} normal notifications")
    finally:
        db.close()

def start_notification_worker():
    scheduler.add_job(
        detect_and_create_notifications,
        "interval",
        minutes=NOTIFICATION_CHECK_INTERVAL_MINUTES,
        id="notification_detector",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"🚀 Notification worker started (interval: {NOTIFICATION_CHECK_INTERVAL_MINUTES}min)")
```

**Add to `main.py` startup**:
```python
from app.workers.notification_worker import start_notification_worker

@app.on_event("startup")
async def startup_event():
    start_canon_worker()       # Existing
    start_notification_worker() # NEW
```

---

## 3. Activity Summary Generation (How It Works)

### Current Flow (From Activity Manager)

**File**: `app/services/activity_manager.py`

```python
def generate_activity_summary(content: str, action_type: str = "message") -> str:
    """
    Generate concise AI summary using GPT-4o-mini.
    Examples:
    - 'Working on API authentication bug'
    - 'Planning Q4 marketing strategy'
    - 'Polishing ParallelOS UX design'
    """
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "system",
            "content": "Summarize user activity in 5-10 words..."
        }, {
            "role": "user",
            "content": text
        }],
        max_tokens=20,
        temperature=0,
    )
    return resp.choices[0].message.content.strip()
```

**Embeddings Generation**:
```python
from config import openai_client

def generate_embedding(content: str) -> list[float]:
    """
    Using text-embedding-3-small: $0.02 per 1M tokens
    Returns 1536-dimensional vector
    """
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=content[:8000],  # Truncate to max length
    )
    return response.data[0].embedding
```

**Similarity Detection**:
```python
STATUS_UPDATE_THRESHOLD = 0.85  # If >85% similar, skip status update
ACTIVITY_LOG_THRESHOLD = 0.75   # If >75% similar, skip logging

def calculate_cosine_similarity(emb1, emb2) -> float:
    """Returns 0.0 to 1.0"""
    dot_product = sum(a * b for a, b in zip(emb1, emb2))
    magnitude1 = sum(a * a for a in emb1) ** 0.5
    magnitude2 = sum(b * b for b in emb2) ** 0.5
    return dot_product / (magnitude1 * magnitude2)
```

### ✅ Summary: Activities are AI-Summarized AFTER Creation
- **Created** via `POST /api/actions` (no summary initially)
- **Processed** by activity manager (generates summary + embedding)
- **Similarity checked** against previous activities
- **Marked as `is_status_change`** if significant enough

**Question Answered**: It's **semi-automatic** - activities created manually, summaries generated asynchronously.

---

## 4. API Endpoints Inventory

### Activity Endpoints

| Endpoint | Method | Purpose | Returns |
|----------|--------|---------|---------|
| `/api/activity/history` | GET | Get activity history with AI summaries | `{activities: [...], total, days}` |
| `/api/activity/feed` | GET | Activity feed (likely for team) | Activity list |
| `/api/team/activity` | GET | Team activity (room-based) | Team activity |
| `/api/actions` | POST | Log a user action | `{status: "logged", session_id}` |

**Parameters**:
- `user_id` (optional) - filter by user
- `days` (default 7) - time range
- `limit` (default 50) - max results

**Filters**:
- Only returns activities with `activity_summary IS NOT NULL`
- Ordered by timestamp DESC

---

### Notification Endpoints ✅

| Endpoint | Method | Purpose | Admin Only? |
|----------|--------|---------|-------------|
| `/api/notifications` | GET | Get user's notifications (limit 50) | No |
| `/api/notifications/unread-count` | GET | Count unread notifications | No |
| `/api/notifications/{id}/mark-read` | POST | Mark notification as read | No |
| `/api/users/{user_id}/notifications` | GET | List user notifications | Self only |
| `/api/users/{user_id}/notifications` | POST | Create notification | Any |

**Missing Endpoints** (Needed):
- `GET /api/notifications?severity=urgent` - Filter by severity
- `GET /api/teams/{team_id}/notifications` - Manager view
- `DELETE /api/notifications/{id}` - Dismiss notification
- `POST /api/notifications/mark-all-read` - Bulk mark read

---

### Team/Manager Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/team/members` | GET | Get team members in user's org |
| `/api/team/activity` | GET | Get team activity (needs room_id?) |
| `/api/rooms` | GET | List rooms (likely exists) |

**Missing Endpoints** (Needed for Manager Dashboard):
- `GET /api/teams/{team_id}/activity` - All members' activity
- `GET /api/teams/{team_id}/conflicts` - Detected conflicts
- `GET /api/teams/{team_id}/stats` - Aggregated metrics
- `GET /api/users/{user_id}/activity` - Individual activity (exists as `/activity/history`)

---

## 5. RAG Implementation ⭐

### Vector Store: **pgvector 0.8.1** (In Postgres!)

**File**: `app/services/rag.py`

**Architecture**:
```
User Query → OpenAI Embedding → pgvector Search → Relevant Messages
```

**Key Function**:
```python
def get_relevant_context(
    db: Session,
    query: str,
    room_id: Optional[str] = None,
    room_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    limit: int = 10,
    similarity_threshold: float = 0.7,
    max_age_days: Optional[int] = 90,
) -> List[MessageORM]:
    """
    Vector similarity search using cosine distance.
    Returns messages sorted by relevance.
    """
    # Generate query embedding
    query_embedding = generate_embedding(query)

    # SQL with pgvector
    sql = text("""
        SELECT
            id,
            1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
        FROM messages
        WHERE
            room_id = ANY(:room_ids)
            AND embedding IS NOT NULL
            AND 1 - (embedding <=> CAST(:query_embedding AS vector)) > :threshold
            AND created_at >= :cutoff
        ORDER BY similarity DESC
        LIMIT :limit
    """)

    result = db.execute(sql, params)
    return messages  # Sorted by similarity
```

**Vector Index** (IVFFlat for speed):
```sql
CREATE INDEX idx_user_actions_embedding
ON user_actions
USING ivfflat (activity_embedding vector_cosine_ops)
WITH (lists='100');
```

**✅ Ready for Activity RAG!**
- Can query: "What did Nayab do with auth in the last week?"
- Just need to add `user_id` and date filters to existing RAG

---

### Example RAG Query for Notifications
```python
# Query user's recent activities semantically
activities = db.execute(text("""
    SELECT
        id, user_id, activity_summary,
        1 - (activity_embedding <=> CAST(:query_embedding AS vector)) as similarity
    FROM user_actions
    WHERE
        user_id = :user_id
        AND activity_embedding IS NOT NULL
        AND timestamp >= NOW() - INTERVAL '7 days'
        AND 1 - (activity_embedding <=> CAST(:query_embedding AS vector)) > 0.7
    ORDER BY similarity DESC
    LIMIT 10
"""), {
    "query_embedding": embedding_str,
    "user_id": user_id
}).fetchall()
```

---

## 6. Conflict Detection (NOT IMPLEMENTED)

### ❌ Current State: No Conflict Detection

**What Exists**:
- File paths CAN be stored in `action_data` JSONB
- Embeddings for semantic similarity
- Room membership for team context

**What's Missing**:
- Logic to compare file paths between users
- Detection of overlapping work windows
- Semantic conflict detection (e.g., both working on "authentication")

---

### 🔧 Recommended Implementation

#### File-Based Conflict Detection
```python
def detect_file_conflicts(db: Session, time_window_hours: int = 24) -> List[dict]:
    """
    Find users working on the same files within time window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=time_window_hours)

    # Get all recent activities with file data
    activities = db.query(UserAction).filter(
        UserAction.timestamp >= cutoff,
        UserAction.action_data.has_key('files')  # Postgres JSONB query
    ).all()

    # Group by file path
    from collections import defaultdict
    file_activity = defaultdict(list)

    for activity in activities:
        files = activity.action_data.get('files', [])
        for file_path in files:
            file_activity[file_path].append({
                'user_id': activity.user_id,
                'timestamp': activity.timestamp,
                'activity': activity.activity_summary
            })

    # Find conflicts (2+ users on same file)
    conflicts = []
    for file_path, activities in file_activity.items():
        if len(set(a['user_id'] for a in activities)) >= 2:
            conflicts.append({
                'file': file_path,
                'users': list(set(a['user_id'] for a in activities)),
                'activities': activities
            })

    return conflicts
```

#### Semantic Conflict Detection
```python
def detect_semantic_conflicts(db: Session, threshold: float = 0.85) -> List[dict]:
    """
    Find users working on semantically similar tasks.
    Uses activity embeddings.
    """
    # Get recent activities from different users in same room
    recent_activities = db.execute(text("""
        SELECT
            a1.id as id1,
            a2.id as id2,
            a1.user_id as user1,
            a2.user_id as user2,
            a1.activity_summary as summary1,
            a2.activity_summary as summary2,
            1 - (a1.activity_embedding <=> a2.activity_embedding) as similarity
        FROM user_actions a1, user_actions a2
        WHERE
            a1.room_id = a2.room_id
            AND a1.user_id != a2.user_id
            AND a1.timestamp >= NOW() - INTERVAL '24 hours'
            AND a2.timestamp >= NOW() - INTERVAL '24 hours'
            AND a1.activity_embedding IS NOT NULL
            AND a2.activity_embedding IS NOT NULL
            AND 1 - (a1.activity_embedding <=> a2.activity_embedding) > :threshold
        ORDER BY similarity DESC
        LIMIT 50
    """), {"threshold": threshold}).fetchall()

    return [
        {
            'users': [row.user1, row.user2],
            'similarity': row.similarity,
            'summaries': [row.summary1, row.summary2],
            'type': 'semantic_overlap'
        }
        for row in recent_activities
    ]
```

---

## 7. VSCode Integration Readiness

### ❌ No VSCode Endpoints Yet

**What Exists**:
- `vscode_auth_codes` table (for OAuth-style auth)
- `user_actions.tool` can be `'vscode'`

**What's Missing**:
- **No POST /api/vscode/activity endpoint**
- No specific schema for VSCode events
- No docs on payload format

---

### 🔧 Recommended Implementation

#### New Endpoint
```python
@api_router.post("/vscode/activity")
async def log_vscode_activity(
    payload: VSCodeActivityPayload,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Log activity from VSCode extension.

    Payload:
    {
        "action_type": "file_opened" | "code_edited" | "command_run" | "llm_chat",
        "data": {
            "file_path": "/path/to/file.py",
            "language": "python",
            "lines_changed": 15,
            "command": "editor.action.formatDocument",
            "chat_message": "How do I implement OAuth?",
            ...
        },
        "session_id": "uuid",
        "timestamp": "2026-01-01T12:00:00Z"
    }
    """
    # Create user action
    user_action = UserAction(
        user_id=current_user.id,
        tool='vscode',
        action_type=payload.action_type,
        action_data=payload.data,
        session_id=payload.session_id,
        timestamp=payload.timestamp or datetime.now(timezone.utc)
    )

    db.add(user_action)
    db.commit()

    # Generate summary asynchronously (or via background job)
    # activity_summary will be populated by activity_manager

    return {"status": "logged", "id": user_action.id}
```

#### Payload Model
```python
from pydantic import BaseModel
from typing import Optional, Dict, Any

class VSCodeActivityPayload(BaseModel):
    action_type: str  # file_opened, code_edited, command_run, llm_chat
    data: Dict[str, Any]  # Flexible JSONB
    session_id: Optional[str] = None
    timestamp: Optional[datetime] = None
```

#### VSCode Extension Format
```typescript
// VSCode extension sends:
{
  action_type: "code_edited",
  data: {
    file_path: "/home/user/project/auth.py",
    language: "python",
    lines_changed: 23,
    change_type: "modification",  // or "creation", "deletion"
    snippet: "def authenticate(user, password):\n    ..."  // First 200 chars
  },
  session_id: "abc-123-def",
  timestamp: "2026-01-01T12:30:00Z"
}
```

---

## 8. Multi-Source Extensibility

### Current Architecture: **Good Foundation**

**✅ Strengths**:
- `user_actions.tool` column supports any source
- `action_data` JSONB allows flexible payloads
- Vector embeddings work across all sources
- APScheduler can run multiple workers

**⚠️ Needs Improvement**:
- No adapter pattern (everything in monolithic endpoints)
- No source-specific validation
- No pluggable conflict detection

---

### 🔧 Recommended: Plugin/Adapter Pattern

#### Base Activity Source
```python
# app/sources/base.py

from abc import ABC, abstractmethod
from typing import List, Dict, Any

class ActivitySource(ABC):
    """Base class for activity sources (VSCode, GitHub, Drive, etc.)"""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return source identifier (e.g., 'vscode', 'github')"""
        pass

    @abstractmethod
    def fetch_activities(
        self,
        user_id: str,
        since: datetime,
        db: Session
    ) -> List[UserAction]:
        """Fetch activities from source API"""
        pass

    @abstractmethod
    def detect_conflicts(
        self,
        activity: UserAction,
        db: Session
    ) -> List[Dict[str, Any]]:
        """Detect conflicts specific to this source"""
        pass

    @abstractmethod
    def validate_payload(self, payload: Dict[str, Any]) -> bool:
        """Validate incoming webhook/API data"""
        pass
```

#### VSCode Source Implementation
```python
# app/sources/vscode_source.py

class VSCodeSource(ActivitySource):
    source_name = "vscode"

    def fetch_activities(self, user_id, since, db):
        # VSCode is push-only (extension sends data)
        # Return recent activities from DB
        return db.query(UserAction).filter(
            UserAction.user_id == user_id,
            UserAction.tool == 'vscode',
            UserAction.timestamp >= since
        ).all()

    def detect_conflicts(self, activity, db):
        """File-based conflict detection for VSCode"""
        file_path = activity.action_data.get('file_path')
        if not file_path:
            return []

        # Find other users editing same file
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        conflicts = db.query(UserAction).filter(
            UserAction.tool == 'vscode',
            UserAction.user_id != activity.user_id,
            UserAction.timestamp >= recent_cutoff,
            UserAction.action_data['file_path'].astext == file_path
        ).all()

        return [{
            'type': 'file_conflict',
            'file': file_path,
            'conflicting_user': c.user_id,
            'their_activity': c.activity_summary
        } for c in conflicts]

    def validate_payload(self, payload):
        required = ['action_type', 'data']
        return all(k in payload for k in required)
```

#### GitHub Source (Future)
```python
# app/sources/github_source.py

class GitHubSource(ActivitySource):
    source_name = "github"

    def fetch_activities(self, user_id, since, db):
        # Fetch from GitHub API
        # Create UserAction entries
        pass

    def detect_conflicts(self, activity, db):
        """PR conflicts, branch conflicts"""
        if activity.action_type == 'pull_request_opened':
            # Check for conflicting PRs
            pass
        return []
```

#### Source Registry
```python
# app/sources/registry.py

class SourceRegistry:
    _sources: Dict[str, ActivitySource] = {}

    @classmethod
    def register(cls, source: ActivitySource):
        cls._sources[source.source_name] = source

    @classmethod
    def get(cls, name: str) -> ActivitySource:
        return cls._sources.get(name)

    @classmethod
    def detect_all_conflicts(cls, activity: UserAction, db: Session) -> List[dict]:
        """Run conflict detection across all registered sources"""
        all_conflicts = []
        source = cls.get(activity.tool)
        if source:
            conflicts = source.detect_conflicts(activity, db)
            all_conflicts.extend(conflicts)
        return all_conflicts

# Register sources
SourceRegistry.register(VSCodeSource())
SourceRegistry.register(GitHubSource())
```

#### Usage in Notification Worker
```python
# app/workers/notification_worker.py

from app.sources.registry import SourceRegistry

async def detect_and_create_notifications():
    db = SessionLocal()
    try:
        # Get recent activities
        recent_activities = db.query(UserAction).filter(
            UserAction.timestamp >= datetime.now(timezone.utc) - timedelta(hours=1),
            UserAction.activity_summary.isnot(None)
        ).all()

        for activity in recent_activities:
            # Detect conflicts using registered sources
            conflicts = SourceRegistry.detect_all_conflicts(activity, db)

            for conflict in conflicts:
                create_urgent_notification(db, {
                    'user_id': activity.user_id,
                    'type': 'conflict',
                    'severity': 'urgent',
                    'title': f"File conflict: {conflict['file']}",
                    'message': f"{conflict['conflicting_user']} is also working on this file",
                    'data': conflict
                })

        db.commit()
    finally:
        db.close()
```

---

## 9. Knowledge Graph / Relationships

### Current State: **Implicit Relationships**

**What We Have**:
- `users.org_id` → `organizations.id`
- `room_members` join table (users ↔ rooms)
- `user_actions.room_id` → `rooms.id`
- `user_actions.task_id` → `tasks.id`
- `notifications.task_id` → `tasks.id`

**What's Missing**:
- No explicit `entity_relationships` table
- No `conflicts_with`, `collaborates_on`, `mentions` relationships
- No relationship strength scores

---

### 🔧 Recommended: Primitive Graph (MVP)

**Option 1**: Use existing foreign keys cleverly
- Query JOIN tables to build graph
- Example: "Users working on same task" = JOIN user_actions on task_id

**Option 2**: Create lightweight relationships table
```sql
CREATE TABLE entity_relationships (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR NOT NULL,  -- 'user', 'activity', 'file', 'task'
    source_id VARCHAR NOT NULL,
    relationship_type VARCHAR NOT NULL,  -- 'conflicts_with', 'collaborates_on', 'mentions', 'edits'
    target_type VARCHAR NOT NULL,
    target_id VARCHAR NOT NULL,
    strength FLOAT DEFAULT 1.0,    -- 0-1 relevance score
    metadata JSONB DEFAULT '{}',   -- Additional context
    created_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(source_type, source_id, relationship_type, target_type, target_id)
);

CREATE INDEX idx_relationships_source ON entity_relationships(source_type, source_id);
CREATE INDEX idx_relationships_target ON entity_relationships(target_type, target_id);
CREATE INDEX idx_relationships_type ON entity_relationships(relationship_type);
```

**Example Data**:
```sql
-- User A conflicts with User B on file X
INSERT INTO entity_relationships VALUES (
    'user', 'user_a_id',
    'conflicts_with',
    'user', 'user_b_id',
    0.9, -- High conflict
    '{"file": "/path/to/auth.py", "reason": "simultaneous_edit"}'
);

-- Activity mentions Task
INSERT INTO entity_relationships VALUES (
    'activity', 'action_123',
    'mentions',
    'task', 'task_456',
    0.8,
    '{"context": "Discussed authentication bug in chat"}'
);
```

**Query Examples**:
```sql
-- Find all users conflicting with User A
SELECT target_id, strength, metadata
FROM entity_relationships
WHERE source_type = 'user'
  AND source_id = 'user_a_id'
  AND relationship_type = 'conflicts_with'
ORDER BY strength DESC;

-- Find all files User A is editing
SELECT target_id, strength
FROM entity_relationships
WHERE source_type = 'user'
  AND source_id = 'user_a_id'
  AND relationship_type = 'edits'
  AND target_type = 'file';
```

---

## 10. Implementation Plan Preview

### Phase 1: Backend Foundation (Week 1)

#### 1.1 Extend Notification Schema ✅
```bash
# Create migration
alembic revision -m "add_notification_extensions"
```

```python
# In migration file
def upgrade():
    op.add_column('notifications', sa.Column('source_type', sa.String(), nullable=True))
    op.add_column('notifications', sa.Column('source_id', sa.String(), nullable=True))
    op.add_column('notifications', sa.Column('severity', sa.String(), server_default='normal'))
    op.add_column('notifications', sa.Column('context_embedding', Vector(1536), nullable=True))
    op.add_column('notifications', sa.Column('related_users', ARRAY(sa.String()), nullable=True))
    op.add_column('notifications', sa.Column('related_files', ARRAY(sa.Text()), nullable=True))
    op.add_column('notifications', sa.Column('room_id', sa.String(), nullable=True))
    op.add_column('notifications', sa.Column('read_at', sa.DateTime(timezone=True), nullable=True))

    op.create_index('idx_notifications_source', 'notifications', ['source_type', 'source_id'])
    op.create_index('idx_notifications_severity', 'notifications', ['severity'])
    op.execute('CREATE INDEX idx_notifications_embedding ON notifications USING ivfflat (context_embedding vector_cosine_ops)')
```

#### 1.2 Create VSCode Endpoint ✅
```python
# In main.py
@api_router.post("/vscode/activity")
async def log_vscode_activity(...):
    # Implementation from section 7
```

#### 1.3 Add Conflict Detection ✅
```python
# In app/services/conflict_detector.py
def detect_file_conflicts(db, time_window_hours=24):
    # Implementation from section 6

def detect_semantic_conflicts(db, threshold=0.85):
    # Implementation from section 6
```

#### 1.4 Create Notification Worker ✅
```python
# In app/workers/notification_worker.py
async def detect_and_create_notifications():
    # Scan for conflicts
    # Create notifications

def start_notification_worker():
    scheduler.add_job(...)
```

---

### Phase 2: New Endpoints (Week 2)

#### 2.1 Enhanced Notification Endpoints
```python
@api_router.get("/notifications")
async def get_notifications(
    severity: Optional[str] = None,  # NEW: filter by severity
    unread_only: bool = False,       # NEW: filter unread
    source_type: Optional[str] = None,  # NEW: filter by source
    limit: int = 50,
    ...
):
    query = db.query(NotificationORM).filter_by(user_id=current_user.id)

    if severity:
        query = query.filter_by(severity=severity)
    if unread_only:
        query = query.filter_by(is_read=False)
    if source_type:
        query = query.filter_by(source_type=source_type)

    notifications = query.order_by(desc(NotificationORM.created_at)).limit(limit).all()
    return {"notifications": [...]}

@api_router.post("/notifications/mark-all-read")
async def mark_all_read(...):
    db.query(NotificationORM).filter_by(
        user_id=current_user.id,
        is_read=False
    ).update({"is_read": True, "read_at": datetime.now(timezone.utc)})
    db.commit()
    return {"status": "success"}

@api_router.delete("/notifications/{notification_id}")
async def delete_notification(...):
    notif = db.query(NotificationORM).filter_by(
        id=notification_id,
        user_id=current_user.id
    ).first()
    if notif:
        db.delete(notif)
        db.commit()
    return {"status": "deleted"}
```

#### 2.2 Manager Dashboard Endpoints
```python
@api_router.get("/teams/{team_id}/activity")
async def get_team_activity(
    team_id: str,
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all activity for team members"""
    # Get team members
    members = db.query(RoomMember).filter_by(room_id=team_id).all()
    member_ids = [m.user_id for m in members]

    # Get activities
    since = datetime.now(timezone.utc) - timedelta(days=days)
    activities = db.query(UserAction).filter(
        UserAction.user_id.in_(member_ids),
        UserAction.timestamp >= since,
        UserAction.activity_summary.isnot(None)
    ).order_by(desc(UserAction.timestamp)).all()

    return {"activities": [...]}

@api_router.get("/teams/{team_id}/conflicts")
async def get_team_conflicts(team_id: str, ...):
    """Get all detected conflicts in team"""
    # Get recent activities from team
    # Run conflict detection
    # Return conflicts grouped by type
    pass

@api_router.get("/teams/{team_id}/stats")
async def get_team_stats(team_id: str, ...):
    """Aggregated team metrics"""
    # Activity counts by member
    # Conflict counts
    # Collaboration patterns
    pass
```

---

### Phase 3: Frontend Components (Week 3)

#### 3.1 NotificationBanner Component
```typescript
// src/components/NotificationBanner.tsx

interface Notification {
  id: string;
  type: string;
  severity: 'normal' | 'urgent';
  title: string;
  message: string;
  data: any;
  read: boolean;
  created_at: string;
}

export function NotificationBanner() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [expanded, setExpanded] = useState(false);

  const urgentCount = notifications.filter(n => !n.read && n.severity === 'urgent').length;
  const totalCount = notifications.filter(n => !n.read).length;

  return (
    <div className="notification-banner">
      <button onClick={() => setExpanded(!expanded)}>
        {urgentCount > 0 && <span className="urgent">{urgentCount} urgent</span>}
        <span>{totalCount} notifications</span>
      </button>

      {expanded && (
        <NotificationList
          notifications={notifications}
          onMarkRead={markRead}
          onDismiss={dismissNotification}
        />
      )}
    </div>
  );
}
```

#### 3.2 Manager Dashboard
```typescript
// src/pages/ManagerDashboard.tsx

export function ManagerDashboard() {
  const [teamActivity, setTeamActivity] = useState([]);
  const [conflicts, setConflicts] = useState([]);
  const [stats, setStats] = useState({});

  // Fetch team data
  useEffect(() => {
    fetch('/api/teams/my-team/activity').then(r => r.json()).then(setTeamActivity);
    fetch('/api/teams/my-team/conflicts').then(r => r.json()).then(setConflicts);
    fetch('/api/teams/my-team/stats').then(r => r.json()).then(setStats);
  }, []);

  return (
    <div className="manager-dashboard">
      <TeamActivityGraph data={teamActivity} />
      <ConflictList conflicts={conflicts} />
      <CollaborationGraph data={stats} />
    </div>
  );
}
```

---

## 11. Recommended Next Steps

### Immediate (This Week)
1. ✅ **Create VSCode activity endpoint** (`POST /api/vscode/activity`)
2. ✅ **Extend notifications schema** (migration for new columns)
3. ✅ **Implement basic conflict detection** (file-based conflicts)
4. ✅ **Add notification worker** (runs every 15 min)

### Short-term (Next 2 Weeks)
5. ✅ **Add enhanced notification endpoints** (severity filter, mark all read, etc.)
6. ✅ **Implement manager dashboard endpoints** (team activity, conflicts, stats)
7. ✅ **Build frontend NotificationBanner component**
8. ✅ **Build frontend Manager Dashboard**

### Medium-term (Next Month)
9. ⚠️ **Implement plugin/adapter pattern** for extensibility
10. ⚠️ **Add GitHub integration** (webhooks for PR/commit notifications)
11. ⚠️ **Add semantic conflict detection** (using embeddings)
12. ⚠️ **Create entity_relationships table** for knowledge graph

### Long-term (Next Quarter)
13. 🔮 **Upgrade to LangGraph** for complex multi-agent workflows
14. 🔮 **Add Google Drive integration** (file change notifications)
15. 🔮 **Implement collaborative filtering** (suggest who to work with)
16. 🔮 **Add LLM-powered conflict resolution** (suggest merge strategies)

---

## 12. Configuration & Environment

### Required Environment Variables
```bash
# Existing
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://...
RAG_ENABLED=true

# New (Add to .env)
NOTIFICATION_CHECK_INTERVAL_MINUTES=15  # How often to scan for conflicts
CONFLICT_DETECTION_TIME_WINDOW_HOURS=24 # Look back window
FILE_CONFLICT_THRESHOLD=2  # Min users on same file to trigger alert
SEMANTIC_CONFLICT_THRESHOLD=0.85  # Embedding similarity threshold
```

### Startup Configuration
```python
# In main.py

@app.on_event("startup")
async def startup_event():
    """Initialize background workers"""
    from app.workers.canon_worker import start_canon_worker
    from app.workers.notification_worker import start_notification_worker

    # Start existing canon worker
    start_canon_worker()

    # Start new notification worker
    start_notification_worker()

    logger.info("✅ All background workers started")
```

---

## 13. Summary & Recommendations

### ✅ Strong Foundation
- **pgvector** already set up with proper indexes
- **APScheduler** ready for background jobs
- **user_actions** table perfectly designed for multi-source activity
- **RAG** working with vector similarity search
- **Activity Manager** handles deduplication and summaries

### ⚠️ Key Gaps to Fill
1. **VSCode endpoint** (easy - 1 hour)
2. **Conflict detection logic** (medium - 1 day)
3. **Notification worker** (easy - 2 hours)
4. **Schema extensions** (easy - 1 hour + migration)

### 🎯 Recommended Architecture

**Use `user_actions` as Single Source of Truth**:
- All activity (chat, VSCode, GitHub, etc.) → `user_actions` table
- `notifications` table for user-facing alerts only
- Background worker scans `user_actions` and creates `notifications`
- Leverage existing embeddings for conflict detection

**Benefits**:
- No schema duplication
- Easier to add new sources (just add `tool` value)
- Centralized RAG (query all activity semantically)
- Simpler conflict detection (compare activities in one table)

**Extensibility Score After Changes: 9/10** ⭐

---

## Appendix: Quick Reference

### Key Files
- `main.py` - API endpoints
- `app/services/rag.py` - Vector search
- `app/services/activity_manager.py` - Activity summaries
- `app/services/canon.py` - Timeline generation
- `app/workers/canon_worker.py` - Background scheduler
- `models.py` - Database models

### Key Tables
- `user_actions` - Activity tracking (⭐ USE THIS)
- `notifications` - User alerts
- `users`, `rooms`, `organizations` - Team hierarchy
- `messages` - Chat with embeddings

### Key Indexes
- `idx_user_actions_embedding` (ivfflat) - Fast vector search
- `idx_user_actions_status_change` - Status changes only
- `idx_user_actions_timestamp` - Time-based queries

### Database Connection
```bash
psql "postgresql://parallel_db_6gnv_user:mltKupXqk4Oo4s0Nc9hTlx65muzy8qbu@dpg-d4jo21buibrs73f0a1ig-a.oregon-postgres.render.com/parallel_db_6gnv"
```

---

**Report Complete** ✅
**Ready to Build**: Frontend + Backend Extensions
**Estimated Implementation**: 2-3 weeks for MVP
