import { useState } from "react";
import NotificationsPanel from "./NotificationsPanel";
import ActivityFeed from "./ActivityFeed";
import HistoryPanel from "./history/HistoryPanel";
import "./RightPanelDrawer.css";

export default function RightPanelDrawer({ isOpen, onClose, initialTab = "notifications" }) {
  const [tab, setTab] = useState(initialTab);

  if (!isOpen) return null;

  const renderContent = () => {
    if (tab === "notifications") return <NotificationsPanel />;
    if (tab === "activity") return <ActivityFeed />;
    if (tab === "history") return <HistoryPanel />;
    return null;
  };

  return (
    <div className="rp-overlay" onClick={onClose}>
      <div className="rp-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="rp-header">
          <div className="rp-tabs">
            <button
              className={tab === "notifications" ? "active" : ""}
              onClick={() => setTab("notifications")}
            >
              Notifications
            </button>
            <button
              className={tab === "activity" ? "active" : ""}
              onClick={() => setTab("activity")}
            >
              Team Activity
            </button>
            <button
              className={tab === "history" ? "active" : ""}
              onClick={() => setTab("history")}
            >
              History
            </button>
          </div>
          <button className="rp-close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="rp-body">{renderContent()}</div>
      </div>
    </div>
  );
}
