# Admin Debug Dashboard System

This document proposes a pilot-ready admin debug dashboard system across core features. It includes current-state findings, IA/routing, wireframes, component hierarchy, visualization choices, API integration, implementation phases, and effort estimates.

## Discovery: Current Admin Surface
- Route: `/admin` renders `AdminPanel` (org management table + invite codes) wrapped by `ThemeProvider` and `TaskProvider` (see src/pages/AdminPanel.jsx).
- Access: Sidebar adds an "Admin" nav entry when `user.is_platform_admin === true` (see src/components/Sidebar.jsx). Right sidebar hides debug tabs for non-admins (see src/components/RightSidebarPanel.jsx).
- Existing admin-ish debugging: `ActivityHistory` component accepts `isAdmin` to show similarity debug data and auto-refresh behavior. errerewr
- No existing tabbed admin layout, feature-specific dashboards, or debug visualizations beyond org management and the small ActivityHistory debug block.

## Information Architecture & Routing
- Top-level: `/admin` renders `AdminDashboard` with a tab strip and nested routes.
- Tabs (subroutes):
  - `/admin/timeline-debug` (Priority 1)
  - `/admin/vscode-debug`
  - `/admin/collaboration-debug`
  - `/admin/system-overview`
- Default redirect `/admin` -> `/admin/timeline-debug`.
- Providers: reuse existing `ThemeProvider` + `TaskProvider`; optionally wrap admin dashboards with a new `AdminDebugProvider` to share selected users, date ranges, and WebSocket connections.

## Wireframes / Sketches (ASCII)

### Admin Shell (all tabs)
```
+---------------------------------------------------------------------+
| Admin Debug (breadcrumbs)            [User avatar] [Theme toggle]   |
| Tabs: [Timeline Debug] [VSCode Debug] [Collaboration Debug] [System]|
+---------------------------------------------------------------------+
Filters / Context: [UserSelector] [DateRangePicker (when applicable)]
```

### Timeline Debug (priority)
```
Top: [UserSelector]     [RefreshButton (Trigger & Watch)]
Flow: [Calendar 28] -> [Emails 500] -> [Stage0 528] -> [Stage1 520] -> ... -> [Final 12]
Click a stage to expand:
Details (selected stage)   | AI Processing             | Guardrails
+--------------------------+---------------------------+----------------------+
| Stage 4: Semantic Dedup  | Items Sent vs Returned    | Before vs After caps |
| Input 48 -> Output 33    | Categories breakdown      | Backfill triggers    |
| Removed items list       | Validation fixes          | Caps/mins status     |
+--------------------------+---------------------------+----------------------+
Logs (tail + download)
[CRITICAL DEBUG] ...
[Stage 6.5] ...
```

### VSCode Debug
```
UserSelector  DateRangePicker
Activity Timeline (horizontal, hover for detail)
 [====== File Edit ======][= Commit =][= Heartbeat =][=== File Edit ===]
File Edit Heatmap (calendar grid)
Conflict Alerts list (red badges)
Context Request Log (table-like list)
```

### Collaboration Debug
```
MultiUserSelector (1-4)
Interaction Graph (network diagram with colored edges: conflicts, chat, notifications, opportunities)
Notification Feed (filter by selected users)
Chat Activity Timeline (bar/sparkline per day)
Conflict / Opportunity List (grouped, sortable)
```

### System Overview
```
Metric cards: Active users, API latency, queue depth, feature usage
Charts: overall activity timeline, error rate sparkline, usage by feature
Tables: top noisy users, top errors
```

## Component Hierarchy (proposed)
```
src/components/admin/
  AdminDashboard.jsx          // Shell + tabs + routing guard
  UserSelector.jsx
  MultiUserSelector.jsx
  DateRangePicker.jsx
  shared/
    MetricCard.jsx
    LogViewer.jsx
    DataTable.jsx
  timeline/
    TimelineDebugDashboard.jsx
    StageFlowDiagram.jsx
    StageDetailsPanel.jsx
    AIProcessingPanel.jsx
    GuardrailsPanel.jsx
    LogsViewer.jsx
  vscode/
    VSCodeDebugDashboard.jsx
    ActivityTimeline.jsx
    FileEditHeatmap.jsx
    ConflictAlert.jsx
    ContextRequestLog.jsx
  collaboration/
    CollaborationDebugDashboard.jsx
    InteractionGraph.jsx
    NotificationFeed.jsx
    ChatActivityTimeline.jsx
    ConflictOpportunityList.jsx
  system/
    SystemOverviewDashboard.jsx
    SystemHealthPanel.jsx
    FeatureUsageStats.jsx
    UserActivityOverview.jsx
```

## Visualization Strategy
- Flow diagrams: `reactflow` (fast to wire boxes/edges + click handlers); fallback simple SVG if perf or bundle is a concern.
- Timelines: `react-chrono` for horizontal timelines with custom content; small custom bar timeline if lighter weight is needed.
- Network graphs: `react-force-graph` or `react-cytoscapejs` (choose based on backend graph data shape; force-graph is lighter to start).
- Heatmaps: `react-calendar-heatmap` for commit-style cells; Recharts custom cell grid as backup.
- Charts/cards: Recharts already used elsewhere? (not detected; if absent, add lightweight Recharts for sparkline and bar charts).
- Tables: `@tanstack/react-table` for virtualizable, sortable tables; AG Grid if heavy data is expected later.
- Logs: Simple virtualized list (e.g., `react-window`) with sticky header, plus download button.

## API Integration Plan
- Auth: reuse existing session (AdminPanel already fetches `/api/me`); guard admin routes client-side using `is_platform_admin`.
- Timeline Debug
  - `GET /api/admin/timeline-debug/:userEmail` -> stages, counts, AI processing, guardrail state, removed items.
  - `POST /api/admin/timeline-debug/:userEmail/refresh` to trigger refresh.
  - `WS /ws/timeline-debug/:userEmail` -> push stage updates and log lines (merge into flow + log tail).
- VSCode Debug
  - `GET /api/admin/vscode-debug/:userEmail?start_date&end_date` -> events (file edits, commits, heartbeats), conflicts, heatmap aggregates, context requests.
- Collaboration Debug
  - `GET /api/admin/collaboration-debug?users[]=...&days=7` -> graph nodes/edges, notifications, chat counts, conflicts/opportunities.
- System Overview
  - `GET /api/admin/system-overview?days=7` -> feature usage stats, error rates, queue metrics, active users list.
- Client behavior: cache per tab, refetch on filters, merge WS payloads where available, show last-updated timestamp, provide CSV/JSON download per panel for debugging handoff.

## Implementation Phases (priority order)
1) Foundation (0.5-1 day): Add `/admin/*` tabbed shell, guards, reusable selectors (UserSelector, MultiUserSelector, DateRangePicker), shared MetricCard/LogViewer/DataTable.
2) Timeline Debug (1.5-2 days): Flow diagram, stage details drawer, AI processing + guardrails panels, log tail with WS, refresh trigger; mock data scaffolding if backend not ready.
3) VSCode Debug (1-1.5 days): Activity timeline, heatmap, conflict alerts, context request log, date range filtering.
4) Collaboration Debug (1-1.5 days): Multi-user selection, interaction graph, notification feed, chat timeline, conflict/opportunity list with filters.
5) System Overview (0.5-1 day): Metric cards, usage charts, error/latency sparklines, basic tables for noisy users/errors.
6) Polish & Ops (0.5 day): Loading/empty/error states, download buttons, performance (virtualized logs), accessibility checks.

## Estimated Effort (per dashboard)
- Timeline Debug: High complexity (real-time + expandable flow) -> ~2 days.
- VSCode Debug: Medium -> ~1-1.5 days.
- Collaboration Debug: Medium -> ~1-1.5 days (graph rendering + filters).
- System Overview: Low -> ~0.5-1 day.
- Shared components & shell: ~1 day upfront.

## Additional Notes / Existing Workflows to Respect
- Org management must remain available; consider nesting it under an "Org Management" tab within `/admin` or linking out to existing `AdminPanel` table.
- Current admin-only ActivityHistory debug (similarity metrics) lives in right sidebar; ensure the new dashboards expose equivalent or better visibility so duplicated effort is avoided.
- Admin gating is enforced via `is_platform_admin`; all new routes/components should respect this and fail closed for non-admins.
