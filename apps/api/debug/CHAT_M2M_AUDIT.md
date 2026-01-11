## Chat M2M Audit (room_id bindings)

Scope: endpoints/services still using `chat_instances.room_id` or otherwise assuming single-room chats.

### MUST STAY workspace-scoped (by design)
- app/api/v1/bootstrap.py: bootstrap() uses ChatInstance.room_id to compute latest message cursor per workspace (workspace landing).
- app/api/v1/workspaces.py: room details + message queries filtered by Message.room_id (workspace-specific view).
- app/services/brief_ai.py: summaries/rag use Message.room_id scoped to provided room_ids.
- app/api/oauth.py (room join flows): workspace membership creation is intentionally workspace-bound.

### SHOULD become M2M-aware (future work)
- app/api/v1/vscode.py:
  - _resolve_chat_instance (lines ~146-190) enforces chat.room_id == workspace_id.
  - chats_query (lines ~240+) filters ChatInstance.room_id == workspace_id.
  - message/history queries filter by room_id and will miss chats linked via chat_room_access.
- app/api/v1/debug.py: workspace debug endpoint filters ChatInstance.room_id == workspace_id.
- app/api/integrations.py: _default_room_for_user / inbound handlers assume single default room_id.
- app/api/v1/bootstrap.py: latest message lookup per room_id; could optionally include chat_room_access links for richer cross-room bootstrap.

### LEAVE AS-IS for now (legacy/low impact)
- app/api/v1/sync.py/task_sync portion: tasks remain workspace-scoped.
- app/api/v1/context.py: now uses resolve_workspace_chat_ids; Message fetch still by chat_ids (room_id retained only for tasks).
- Admin endpoints: no admin routes depend on chat.room_id; envelope compliance preserved.

Notes:
- chat_instances.room_id is still NOT NULL; messages still require a room_id. Full nullable migration not attempted.
- New helper resolve_workspace_chat_ids (app/api/v1/deps.py) unifies chat ids from chat_room_access ∪ legacy room_id; currently used by chats list, context-bundle, sync.
