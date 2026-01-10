import React, { useState, useEffect } from "react";
import { getVSCodeDebug, formatAdminError } from "../../../api/adminApi";
import UserSelector from "../UserSelector";
import MetricCard from "../shared/MetricCard";
import "./VSCode.css";

const VSCodeDebugDashboard = () => {
  const [selectedUser, setSelectedUser] = useState("");
  const [startDate, setStartDate] = useState(() => {
    const date = new Date();
    date.setDate(date.getDate() - 7);
    return date.toISOString().split("T")[0];
  });
  const [endDate, setEndDate] = useState(new Date().toISOString().split("T")[0]);
  const [vsCodeData, setVsCodeData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (selectedUser) {
      console.log("💻 [ADMIN/VSCodeDebug] User selected:", selectedUser);
      fetchVsCodeData();
    }
  }, [selectedUser, startDate, endDate]);

  const fetchVsCodeData = async () => {
    console.log("💻 [ADMIN/VSCodeDebug] Fetching VSCode data for:", selectedUser);
    console.log("💻 [ADMIN/VSCodeDebug] Date range:", startDate, "to", endDate);
    setLoading(true);
    setError(null);

    try {
      const data = await getVSCodeDebug(selectedUser, startDate, endDate);
      console.log("💻 [ADMIN/VSCodeDebug] VSCode data received:", data);
      console.log("💻 [ADMIN/VSCodeDebug] Total actions:", data.activity_summary?.total_actions);
      console.log("💻 [ADMIN/VSCodeDebug] VSCode linked:", data.vscode_linked);

      setVsCodeData(data);
    } catch (err) {
      console.error("❌ [ADMIN/VSCodeDebug] Failed to fetch VSCode data:", err);
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="vscode-debug-dashboard">
      {/* Controls */}
      <div className="debug-controls">
        <UserSelector value={selectedUser} onChange={setSelectedUser} placeholder="Select user to debug..." />

        {selectedUser && (
          <div className="date-controls">
            <input
              type="date"
              value={startDate}
              onChange={(e) => {
                console.log("💻 [ADMIN/VSCodeDebug] Start date changed:", e.target.value);
                setStartDate(e.target.value);
              }}
              className="date-input"
            />
            <span>to</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => {
                console.log("💻 [ADMIN/VSCodeDebug] End date changed:", e.target.value);
                setEndDate(e.target.value);
              }}
              className="date-input"
            />
          </div>
        )}
      </div>

      {/* Error State */}
      {error && (
        <div
          className="error-state"
          style={{
            padding: "16px",
            background: "#fee2e2",
            border: "1px solid #ef4444",
            borderRadius: "8px",
            color: "#991b1b",
            margin: "16px 0",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "8px" }}>Failed to load VSCode data</div>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              fontSize: "12px",
              fontFamily: "monospace",
              margin: 0,
            }}
          >
            {formatAdminError(error)}
          </pre>
          {error.status && (
            <details style={{ marginTop: "12px", fontSize: "12px" }}>
              <summary style={{ cursor: "pointer", fontWeight: 500 }}>
                Error Details (HTTP {error.status})
              </summary>
              <pre
                style={{
                  marginTop: "8px",
                  padding: "12px",
                  background: "rgba(0,0,0,0.05)",
                  borderRadius: "4px",
                  overflow: "auto",
                }}
              >
                {JSON.stringify(error, null, 2)}
              </pre>
            </details>
          )}
          <button
            onClick={fetchVsCodeData}
            style={{
              marginTop: "12px",
              padding: "8px 16px",
              background: "#dc2626",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "13px",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Loading State */}
      {loading && <div className="loading-state">Loading VSCode data...</div>}

      {/* Empty State */}
      {!selectedUser && !loading && (
        <div className="empty-state">
          <p>Select a user to view their VSCode activity</p>
        </div>
      )}

      {/* Main Content */}
      {vsCodeData && !loading && !error && (
        <>
          {/* Metrics */}
          <div className="metrics-grid">
            <MetricCard
              title="Total Actions"
              value={vsCodeData.activity_summary?.total_actions || 0}
              subtitle={vsCodeData.vscode_linked ? "✅ Linked" : "❌ Not linked"}
              icon="💻"
            />
            <MetricCard
              title="Code Edits"
              value={vsCodeData.activity_summary?.total_edits || 0}
              subtitle="File saves + edits"
              icon="✏️"
            />
            <MetricCard
              title="Git Commits"
              value={vsCodeData.activity_summary?.total_commits || 0}
              subtitle="In date range"
              icon="📝"
            />
            <MetricCard
              title="Conflicts"
              value={vsCodeData.conflicts_detected?.length || 0}
              subtitle={
                vsCodeData.notifications?.last_conflict_at
                  ? `Last: ${new Date(vsCodeData.notifications.last_conflict_at).toLocaleDateString()}`
                  : "None"
              }
              icon="⚠️"
            />
          </div>

          {/* Files & Projects */}
          <div className="section">
            <h2>Files & Projects</h2>
            <div className="files-projects-grid">
              <div className="info-box">
                <h3>Files Edited ({vsCodeData.activity_summary?.files_count || 0})</h3>
                <div className="files-list">
                  {vsCodeData.activity_summary?.files_edited?.slice(0, 10).map((file, i) => (
                    <div key={i} className="file-item">
                      <span>
                        📄 {file.split("/").pop()}
                      </span>
                      <span className="file-path">{file}</span>
                    </div>
                  )) || <p className="text-gray-500">No files tracked</p>}
                  {vsCodeData.activity_summary?.files_count > 10 && (
                    <p className="text-sm text-gray-500">
                      ...and {vsCodeData.activity_summary.files_count - 10} more
                    </p>
                  )}
                </div>
              </div>

              <div className="info-box">
                <h3>Projects ({vsCodeData.activity_summary?.projects?.length || 0})</h3>
                <div className="projects-list">
                  {vsCodeData.activity_summary?.projects?.map((project, i) => (
                    <div key={i} className="project-item">
                      📁 {project}
                    </div>
                  )) || <p className="text-gray-500">No projects tracked</p>}
                </div>
              </div>
            </div>
          </div>

          {/* Recent Activity */}
          <div className="section">
            <h2>Recent Activity ({vsCodeData.recent_activity?.length || 0})</h2>
            <div className="activity-timeline">
              {vsCodeData.recent_activity?.slice(0, 10).map((activity, i) => (
                <div key={i} className="activity-item">
                  <div className="activity-time">{new Date(activity.timestamp).toLocaleString()}</div>
                  <div className="activity-type">
                    {getActivityIcon(activity.event_type)} {activity.event_type}
                  </div>
                  {activity.action_data && <div className="activity-details">{renderActivityDetails(activity.action_data)}</div>}
                </div>
              )) || <p className="text-gray-500">No recent activity</p>}
            </div>
          </div>

          {/* Conflicts */}
          {vsCodeData.conflicts_detected?.length > 0 && (
            <div className="section">
              <h2>Conflicts Detected ({vsCodeData.conflicts_detected.length})</h2>
              <div className="conflicts-list">
                {vsCodeData.conflicts_detected.map((conflict, i) => (
                  <div key={i} className="conflict-item">
                    <div className="conflict-header">
                      <span className={`conflict-type ${conflict.conflict_type}`}>
                        {conflict.conflict_type === "file" ? "📄 File Conflict" : "🔍 Semantic Conflict"}
                      </span>
                      <span className="conflict-time">{new Date(conflict.timestamp).toLocaleString()}</span>
                    </div>
                    <div className="conflict-title">{conflict.title}</div>
                    <div className="conflict-message">{conflict.message}</div>
                    {conflict.read ? (
                      <span className="conflict-status read">✅ Read</span>
                    ) : (
                      <span className="conflict-status unread">⚠️ Unread</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

function getActivityIcon(eventType) {
  const icons = {
    code_edit: "✏️",
    file_save: "💾",
    git_commit: "📝",
    debug_session: "🐛",
  };
  return icons[eventType] || "💻";
}

function renderActivityDetails(actionData) {
  if (typeof actionData === "string") {
    try {
      actionData = JSON.parse(actionData);
    } catch {
      return <span>{actionData}</span>;
    }
  }

  if (!actionData || typeof actionData !== "object") {
    return null;
  }

  return (
    <div className="action-data">
      {actionData.file_path && <div>File: {actionData.file_path}</div>}
      {actionData.lines_added !== undefined && (
        <div>
          +{actionData.lines_added} -{actionData.lines_deleted || 0}
        </div>
      )}
      {actionData.commit_message && <div>"{actionData.commit_message}"</div>}
      {actionData.project_name && <div>Project: {actionData.project_name}</div>}
    </div>
  );
}

export default VSCodeDebugDashboard;
