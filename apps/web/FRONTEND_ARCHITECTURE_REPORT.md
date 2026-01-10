# Frontend Architecture Report

## File Structure
- Routes/entry: `src/App.jsx` (routes `/` → `LandingPage`; `/app/*` → dashboard shell with Manager/Intelligence via internal tab state; `/admin/*` admin shell).
- Manager page: `src/pages/Manager.jsx`, styles `src/pages/Manager.css`.
- Intelligence page: `src/pages/Intelligence.jsx`, styles `src/pages/Intelligence.css`.
- Dashboard host: `src/pages/Dashboard.jsx` (renders Manager/Intelligence based on `activeTool` and sidebar).
- Org graph: `src/components/brief/OrgIntelligenceGraph.jsx` (+ `OrgIntelligenceGraph.css`).
- Timeline/daily brief: `src/pages/DailyBrief.jsx` (tabs include “Org” which mounts `OrgIntelligenceGraph`).
- Chat/LLM: `src/components/ChatPanel.jsx` (used inside `Dashboard.jsx`), intelligence assistant chat logic in `src/pages/Intelligence.jsx`.
- Room management UI: in Manager page (above), plus room API helpers in `src/lib/tasksApi.js`.
- Notifications: `src/components/NotificationsPanel.jsx`, `src/components/RightSidebarPanel.jsx` (admin-only tabs + activity/history/notifications).

## Manager Page
- Route: via dashboard internal tab (`activeTool === "Manager"` in `src/pages/Dashboard.jsx`), path `/app/*` with tab selection from sidebar.
- Main Component: `src/pages/Manager.jsx`.
- Current Tabs: Team, Rooms (`tabs` array).
- Child Components/Hierarchy: Manager → tab buttons → tab panels (Team list with toggles; Rooms matrix) using framer-motion for transitions; direct DOM, no nested custom components.
- API Calls:
  - `fetchTeam()`, `listRooms()`, `getUserRooms(userId)`, `updateUserRooms(userId, roomIds)`, `createRoom()`, `deleteRoom()` from `src/lib/tasksApi.js`.
  - Direct POST `/api/users/{userId}/manager` to toggle manager access.
- State Management: React hooks (`useState`, `useEffect`), UI state in component.
- Routing: selected via sidebar entry “Manager” in `src/components/Sidebar.jsx`; `Dashboard.jsx` sets `activeTool` and renders `<Manager />`.

## Intelligence Page
- Route: via dashboard tab `activeTool === "Intelligence"` (default), path `/app/*`.
- Main Component: `src/pages/Intelligence.jsx`.
- Features/Sections:
  - Personal assistant chat: loads/creates assistant chat via `/api/assistant/chat`; fetches messages from stored chat ID.
  - Daily Brief/Canon plan: uses `DailyBrief` component (`src/pages/DailyBrief.jsx`) with tabs.
  - Org graph appears on DailyBrief tab “Org” (`OrgIntelligenceGraph`).
- Child Hierarchy: Intelligence → header and assistant panel (ChatPanel-like UI inline) + `DailyBrief`.
- API Calls: `/api/me`, `/api/assistant/chat`, `/api/assistant/messages`/`/api/assistant/message` (send), preferences from `/api/me` for refresh interval. Uses `API_BASE_URL` fetch with credentials.
- State Management: React hooks; some localStorage for assistant chat/room IDs; no Redux.
- Route Path: rendered under `/app/*` via dashboard tab.

## Org Graph Component
- Location: `src/components/brief/OrgIntelligenceGraph.jsx`.
- Coupling: Reusable component, imported by `DailyBrief.jsx` (Org tab).
- Props: None currently; uses internal mock data (`MOCK_ROOMS`, `MOCK_EDGES`) and utilities from `src/utils/orgCalculations`.
- Data Display: Rooms with status/fires/overdue/sentiment, members; edges with overlap/strength. Uses mock data; utilities suggest future real data from `getRooms`, `getRoomMembers`, `getActivityHistory`, `getNotifications`, `getOrgGraphData`.
- Libraries: `@xyflow/react` (ReactFlow) for graph, CSS in `OrgIntelligenceGraph.css`.
- Structure: defines RoomNode, edge calculations, and renders ReactFlow with controls/minimap/background.

## Timeline/Daily Brief Component
- Location: `src/pages/DailyBrief.jsx` (large multi-tab brief).
- Reusability: Page-level but can be embedded; exposes tabs including “Org” (graph), “Brief”, etc.
- Data Display: Daily/weekly/monthly items, summaries; uses props/state inside file; pulls data via brief-related APIs (see file for specifics).
- API: Uses `API_BASE_URL` fetches within DailyBrief for brief data; not a shared hook.
- Structure: Tabs, sections for recap, tasks, org graph insertion.

## Chat/LLM Interface
- Primary component: `src/components/ChatPanel.jsx` used in dashboard main area; handles rooms/chats.
- API Endpoints: From `src/lib/tasksApi.js`: `createChat`, `getChatMessages`, `listAllChats`, `sendMessage` (naming inside tasksApi). In Intelligence assistant, direct fetch `/api/assistant/message` (send) and `/api/assistant/messages` (history) tied to chatId.
- Display: ChatPanel renders message list, composer, uses props for messages/handlers; Intelligence page renders assistant chat inline with its own state.
- Context: Dashboard passes `currentUser`, room/chat ids; assistant chat stores chatId/roomId in localStorage; message send includes room/chat context.

## Room Management
- Location: Manager page (`src/pages/Manager.jsx`), Rooms tab.
- Operations: List rooms, create room (newRoomName), delete room, assign users to rooms (matrix toggle), enforce at least one room membership, toggle manager access.
- API Calls: `listRooms`, `createRoom`, `deleteRoom`, `getUserRooms`, `updateUserRooms` (tasksApi); POST `/api/users/{id}/manager` for manager access.
- UI Components: Inline in Manager; uses framer-motion for tab transitions, checkboxes for membership/permissions.

## Notification System
- Display Components: `src/components/NotificationsPanel.jsx`, referenced in `src/components/RightSidebarPanel.jsx` under admin-only tabs; also notifications shown in collaboration debug (admin) and Org graph utilities.
- Placement: Right sidebar in dashboard (admin-only tab "Alerts" in RightSidebarPanel); Collaboration debug has notification feed section.
- Fetching: NotificationsPanel fetches via notification APIs (`src/api/notificationApi.js`) with polling/refresh hooks; RightSidebarPanel auto-refresh timer option.
- Mechanism: HTTP polling; no WebSocket wiring in these components.

## Component Dependencies
- Dashboard shell (`src/pages/Dashboard.jsx`) orchestrates tabs (Intelligence, Manager, VSCode, Settings).
- Sidebar (`src/components/Sidebar.jsx`) drives `activeTool`.
- Manager imports tasks API helpers.
- Intelligence imports DailyBrief and uses assistant endpoints.
- OrgIntelligenceGraph imports orgApi utilities and ReactFlow.
- NotificationsPanel/RightSidebarPanel imports notificationApi/activity/history components.

## Routing Summary
- `/` and `/index.html` → `LandingPage.jsx`.
- `/app/*` → dashboard (`Dashboard.jsx` via AppLayout), internal tabs: Intelligence (default), Manager, VSCode, Settings, etc.
- `/app/vscode` redirect present; no standalone manager route beyond tab selection.
- `/admin/*` → admin dashboards (separate, not covered here).
