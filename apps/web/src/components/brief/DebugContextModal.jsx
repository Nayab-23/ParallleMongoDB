import { useState } from "react";

export default function DebugContextModal({ context = {}, onClose }) {
  const [tab, setTab] = useState("emails");

  const dataSources = context.data_sources || {};
  const raw = context.raw_context || {}; // asdsadsa

  return (
    <div className="debug-modal-overlay" onClick={onClose}>
      <div className="debug-modal" onClick={(e) => e.stopPropagation()}>
        <div className="debug-header">
          <h2>🔍 AI Context Debug</h2>
          <button onClick={onClose}>✕</button>
        </div>

        <div className="debug-stats">
          <span>📧 {dataSources.emails_count ?? 0} emails</span>
          <span>📅 {dataSources.calendar_events_count ?? 0} events</span>
          <span>💬 {dataSources.team_messages_count ?? 0} messages</span>
        </div>

        <div className="debug-tabs">
          <button onClick={() => setTab("emails")} className={tab === "emails" ? "active" : ""}>
            Emails
          </button>
          <button onClick={() => setTab("calendar")} className={tab === "calendar" ? "active" : ""}>
            Calendar
          </button>
          <button onClick={() => setTab("team")} className={tab === "team" ? "active" : ""}>
            Team Activity
          </button>
          <button onClick={() => setTab("raw")} className={tab === "raw" ? "active" : ""}>
            Raw JSON
          </button>
        </div>

        <div className="debug-content">
          {tab === "emails" && <pre>{raw.emails || "No email context"}</pre>}
          {tab === "calendar" && <pre>{raw.calendar || "No calendar context"}</pre>}
          {tab === "team" && <pre>{raw.team_activity || "No team context"}</pre>}
          {tab === "raw" && <pre>{JSON.stringify(context, null, 2)}</pre>}
        </div>

        <div className="debug-footer">
          <button
            onClick={() => {
              navigator.clipboard.writeText(JSON.stringify(context, null, 2));
            }}
          >
            📋 Copy to Clipboard
          </button>
          <button
            onClick={() => {
              const blob = new Blob([JSON.stringify(context, null, 2)], { type: "application/json" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `debug-context-${Date.now()}.json`;
              a.click();
            }}
          >
            💾 Download JSON
          </button> 
        </div>
      </div>
    </div>
  );
}
