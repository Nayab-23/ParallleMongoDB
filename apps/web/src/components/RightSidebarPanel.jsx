import { useEffect } from "react";
import SummaryPanel from "./SummaryPanel";
import TeamPanel from "./TeamPanel";
import NotificationsPanel from "./NotificationsPanel";
import HistoryPanel from "./history/HistoryPanel";
import ActivityHistory from "./activity/ActivityHistory";
import "./RightSidebarPanel.css";

function TeamView({ user, statuses = [], liveLog = [] }) {
  const summarize = (text) => {
    if (!text) return "thinking…";
    const cleaned = text.replace(/\s+/g, " ").trim();
    if (cleaned.length <= 100) return cleaned;
    return cleaned.slice(0, 97) + "…";
  };

  return (
    <div className="chat-wrapper glass">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Live work</p>
          <h2>Team activity</h2>
        </div>
      </div>

      <TeamPanel user={user} statuses={statuses} />
      <p className="subhead">Updates stream here when Team is selected.</p>

      <div className="team-live-log">
        <div className="team-live-log-header">
          <p className="eyebrow">Live log</p>
        </div>

        {(!liveLog || liveLog.length === 0) && (
          <p className="subhead">No recent teammate messages yet.</p>
        )}

        {liveLog && liveLog.length > 0 && (
          <ul className="team-live-log-list">
            {liveLog.map((entry) => (
              <li key={entry.id} className="team-live-log-row">
                <span className="team-live-log-name">{entry.name}</span>
                <span className="team-live-log-text">
                  is working on: {summarize(entry.content)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function RightSidebarPanel({
  activeTool = "Chat",
  rightSidebarView = "summary",
  user = null,
  teamStatuses = [],
  liveLog = [],
  activityLog = [],
  roomData = null,
  historyRefreshKey = 0,
  onAutoRefreshHistory = null,
  onRightSidebarViewChange = null,
}) {
  // Optional auto-refresh hook for history/notifications
  useEffect(() => {
    if (typeof onAutoRefreshHistory !== "function") return undefined;
    const timer = setInterval(() => {
      onAutoRefreshHistory();
    }, 30000);
    return () => clearInterval(timer);
  }, [onAutoRefreshHistory]);

  const tabs = [
    { id: "summary", label: "Activity", icon: "👥", description: "Team status & activity" },
    { id: "notifications", label: "Alerts", icon: "🔔", description: "Notifications" },
    { id: "history", label: "History", icon: "📋", description: "Task history" },
  ];

  // Check if user is admin
  const isAdmin = user?.is_platform_admin === true;

  if (activeTool === "Manager") return <div className="dashboard-right"><SummaryPanel user={user} activityLog={activityLog} roomData={roomData} /></div>;
  if (activeTool === "Team")
    return (
      <div className="dashboard-right">
        <TeamView user={user} statuses={teamStatuses} liveLog={liveLog} />
      </div>
    );
  if (activeTool === "IDE")
    return (
      <div className="dashboard-right">
        {/* IDE-specific right content could go here; keeping empty to match previous UX */}
      </div>
    );

  // Hide right sidebar tabs for non-admin users
  if (!isAdmin) {
    return <div className="dashboard-right" />;
  }

  return (
    <div className="dashboard-right">
      <div className="dashboard-right-container">
        {/* Main content area */}
        <div className="sidebar-content-area">
          {rightSidebarView === "summary" && (
            <div className="activity-section">
              <SummaryPanel
                user={user}
                activeTool={activeTool}
                activityLog={activityLog}
                roomData={roomData}
              />
              <ActivityHistory days={7} isAdmin={isAdmin} />
            </div>
          )}
          {rightSidebarView === "notifications" && <NotificationsPanel user={user} />}
          {rightSidebarView === "history" && (
            <HistoryPanel refreshToken={historyRefreshKey} />
          )}
        </div>

        {/* Vertical tab strip on the right edge */}
        <div className="sidebar-tab-strip">
          {tabs.map(tab => (
            <button
              key={tab.id}
              className={`sidebar-tab-vertical ${rightSidebarView === tab.id ? 'active' : ''}`}
              onClick={() => onRightSidebarViewChange(tab.id)}
              title={tab.description}
            >
              <span className="tab-icon-vertical">{tab.icon}</span>
              <span className="tab-label-vertical">{tab.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
