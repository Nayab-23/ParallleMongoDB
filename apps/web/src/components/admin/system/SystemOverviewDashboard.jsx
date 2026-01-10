import React, { useEffect, useRef, useState } from "react";
import MetricCard from "../shared/MetricCard";
import { getSystemOverview, formatAdminError, getAdminEvents } from "../../../api/adminApi";
import MultiUserSelector from "../MultiUserSelector";
import { ReactFlow, Background, MiniMap, Controls } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./System.css";

const SystemOverviewDashboard = () => {
  const [days, setDays] = useState(7);
  const [systemData, setSystemData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [contractError, setContractError] = useState(null);
  const [legacyInfo, setLegacyInfo] = useState(null);
  const [lastMeta, setLastMeta] = useState({ request_id: null, duration_ms: null });
  const [events, setEvents] = useState([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState(null);
  const [eventsDays, setEventsDays] = useState(7);
  const [eventsUsers, setEventsUsers] = useState([]);
  const [eventsTypes, setEventsTypes] = useState("");
  const [selectedEvent, setSelectedEvent] = useState(null);
  const controllerRef = useRef(null);
  const seqRef = useRef(0);
  const eventsControllerRef = useRef(null);
  const eventsSeqRef = useRef(0);

  useEffect(() => {
    fetchSystemData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days]);

  useEffect(() => {
    fetchEvents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventsDays, eventsUsers, eventsTypes]);

  const fetchSystemData = async () => {
    if (controllerRef.current) controllerRef.current.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const seq = ++seqRef.current;
    setLoading(true);
    setError(null);
    setContractError(null);
    try {
      const resp = await getSystemOverview(days, { signal: controller.signal });
      if (seq !== seqRef.current) return;
      setLegacyInfo(resp?.debug?.legacy ? { request_id: resp?.request_id, status: resp?.status, endpoint: resp?.debug?.url } : null);
      setLastMeta({ request_id: resp?.request_id, duration_ms: resp?.duration_ms });
      if (!resp?.success) {
        setError({
          message: resp?.error?.message || "Failed to load system data",
          status: resp?.status,
          request_id: resp?.request_id,
          duration_ms: resp?.duration_ms,
          details: resp?.error?.details || resp?.error,
        });
        setSystemData(null);
        return;
      }
      const payload = resp?.data ?? {};
      const requiredOk =
        payload.date_range &&
        payload.users &&
        payload.timeline &&
        payload.communication &&
        payload.notifications &&
        payload.feature_usage &&
        Array.isArray(payload.daily_activity);
      if (!requiredOk) {
        console.error("[Admin/SystemOverview] Contract mismatch", { request_id: resp?.request_id, endpoint: resp?.debug?.url, payload });
        setContractError({
          message: "Contract mismatch",
          request_id: resp?.request_id,
          duration_ms: resp?.duration_ms,
        });
        setSystemData(null);
        return;
      }
      setSystemData(payload);
    } catch (err) {
      console.error("Failed to fetch system data:", err);
      if (seq !== seqRef.current) return;
      setError({ message: err?.message || "Failed to load system data", status: err?.status });
      setSystemData(null);
    } finally {
      if (seq === seqRef.current) {
        setLoading(false);
      }
    }
  };

  const fetchEvents = async () => {
    if (eventsControllerRef.current) eventsControllerRef.current.abort();
    const controller = new AbortController();
    eventsControllerRef.current = controller;
    const seq = ++eventsSeqRef.current;
    setEventsLoading(true);
    setEventsError(null);
    setSelectedEvent(null);
    try {
      const users = Array.isArray(eventsUsers) ? eventsUsers : [];
      const types = eventsTypes
        ? eventsTypes
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean)
        : [];
      const resp = await getAdminEvents(eventsDays, users, types, { signal: controller.signal });
      if (seq !== eventsSeqRef.current) return;
      setLegacyInfo((prev) =>
        prev || resp?.debug?.legacy
          ? { request_id: resp?.request_id, status: resp?.status, endpoint: resp?.debug?.url }
          : prev
      );
      if (!resp?.success) {
        setEventsError({
          message: resp?.error?.message || resp?.error || "Failed to fetch events",
          request_id: resp?.request_id,
          status: resp?.status,
          details: resp?.error?.body || resp?.error,
        });
        setEvents([]);
        return;
      }
      const evts = resp?.data?.events ?? resp?.events ?? [];
      setEvents(Array.isArray(evts) ? evts : []);
    } catch (err) {
      if (seq !== eventsSeqRef.current) return;
      setEventsError({
        message: err?.message || "Failed to fetch events",
        status: err?.status,
      });
      setEvents([]);
    } finally {
      if (seq === eventsSeqRef.current) {
        setEventsLoading(false);
      }
    }
  };

  const buildNodes = (evts) => {
    try {
      const users = Array.from(new Set(evts.flatMap((e) => [e.user, e.target_user]).filter(Boolean)));
      const userIndex = Object.fromEntries(users.map((u, idx) => [u, idx]));
      const sorted = Array.isArray(evts)
        ? [...evts].sort((a, b) => new Date(a.timestamp || 0) - new Date(b.timestamp || 0))
        : [];
      return sorted.map((ev, idx) => {
        const lane = userIndex[ev.user] ?? 0;
        return {
          id: ev.id || `ev-${idx}`,
          position: { x: lane * 220, y: idx * 80 },
          data: { label: `${ev.type || "event"}\n${ev.user || ""}` },
          style: {
            padding: 8,
            borderRadius: 6,
            border: "1px solid #e5e7eb",
            background: "#f9fafb",
            fontSize: 12,
            whiteSpace: "pre-wrap",
          },
        };
      });
    } catch (err) {
      console.error("Failed to build nodes:", err);
      return [];
    }
  };

  const buildEdges = (evts) => {
    const edgesList = [];
    // Edges can be added when backend provides explicit source->target event ids.
    return edgesList;
  };

  const handleNodeClick = (node) => {
    const ev = events.find((e, idx) => (e.id || `ev-${idx}`) === node.id);
    setSelectedEvent(ev || null);
  };

  const dailyActivity = systemData?.daily_activity || [];
  const maxActivity = dailyActivity.reduce((max, day) => Math.max(max, day.total || 0), 0) || 1;

  return (
    <div className="system-overview-dashboard">
      <div className="debug-controls" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div className="error-meta">last request_id: {lastMeta.request_id || "—"}</div>
          <div className="error-meta">duration_ms: {lastMeta.duration_ms ?? "—"}</div>
          <a href="/api/admin/_health" target="_blank" rel="noreferrer" className="error-meta">/api/admin/_health</a>
          <a href="/api/admin/_routes" target="_blank" rel="noreferrer" className="error-meta">/api/admin/_routes</a>
        </div>
      </div>

      {legacyInfo && (
        <div className="error-state" style={{ marginTop: 8 }}>
          <div style={{ fontWeight: 600 }}>Non-enveloped admin response</div>
          <div className="error-meta">endpoint: {legacyInfo.endpoint}</div>
          <div className="error-meta">request_id: {legacyInfo.request_id || "n/a"}</div>
          <div className="error-meta">status: {legacyInfo.status ?? "n/a"}</div>
        </div>
      )}

      <div className="debug-controls">
        <div className="days-selector">
          <label>Time Range:</label>
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value, 10))} className="days-select">
            <option value={1}>Last 24 hours</option>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        </div>

        <button onClick={fetchSystemData} className="refresh-btn">
          🔄 Refresh
        </button>
      </div>

      {systemData && (
        <div className="section">
          <h2>Daily Activity</h2>
          {dailyActivity.length === 0 ? (
            <div className="empty-state">No daily activity data</div>
          ) : (
            <>
              <div className="activity-chart">
                {dailyActivity.map((day, index) => {
                  const heightPercentage = ((day.total || 0) / maxActivity) * 100;
                  return (
                    <div key={index} className="chart-bar-container">
                      <div
                        className="chart-bar"
                        style={{ height: `${Math.max(heightPercentage, 2)}%` }}
                        title={`${day.date}: ${day.total} total (${day.actions || 0} actions, ${day.messages || 0} messages)`}
                      >
                        <div
                          className="chart-bar-actions"
                          style={{ height: `${((day.actions || 0) / Math.max(day.total || 1, 1)) * 100}%` }}
                        />
                        <div
                          className="chart-bar-messages"
                          style={{ height: `${((day.messages || 0) / Math.max(day.total || 1, 1)) * 100}%` }}
                        />
                      </div>
                      <div className="chart-label">
                        {new Date(day.date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="chart-legend">
                <span><span className="legend-box actions"></span> Actions</span>
                <span><span className="legend-box messages"></span> Messages</span>
              </div>
            </>
          )}
        </div>
      )}

      <div className="section">
        <h2>Activity Graph (Beta)</h2>
        <div className="debug-controls">
          <div className="days-selector">
            <label>Days:</label>
            <select value={eventsDays} onChange={(e) => setEventsDays(parseInt(e.target.value, 10))} className="days-select">
              <option value={1}>1</option>
              <option value={7}>7</option>
              <option value={14}>14</option>
            <option value={30}>30</option>
          </select>
        </div>
          <div style={{ minWidth: 260, flex: 1 }}>
            <MultiUserSelector selected={eventsUsers} onChange={setEventsUsers} max={6} placeholder="Filter users..." />
          </div>
          <input
            className="user-selector"
            placeholder="Filter types (comma-separated)"
            value={eventsTypes}
            onChange={(e) => setEventsTypes(e.target.value)}
            style={{ maxWidth: 220 }}
          />
          <button className="refresh-btn" onClick={fetchEvents} disabled={eventsLoading}>
            {eventsLoading ? "Loading..." : "Refresh"}
          </button>
        </div>

        {eventsError && (
          <div className="error-state">
            <div style={{ fontWeight: 600 }}>Events fetch failed</div>
            <div>{eventsError.message || "Unknown error"}</div>
            {eventsError.status !== undefined && (
              <div className="error-meta">status: {eventsError.status}</div>
            )}
            {eventsError.request_id && <div className="error-meta">request_id: {eventsError.request_id}</div>}
            {eventsError.details && (
              <details style={{ marginTop: 8 }}>
                <summary>Details</summary>
                <pre className="error-body">{JSON.stringify(eventsError.details, null, 2)}</pre>
              </details>
            )}
          </div>
        )}

        {eventsLoading && !events.length && <div className="loading-state">Loading activity graph...</div>}
        {!eventsLoading && !eventsError && events.length === 0 && <div className="empty-state">No events found.</div>}

        {!eventsLoading && events.length > 0 && (
          <div className="activity-graph-shell">
            <div style={{ height: Math.max(events.length * 80 + 200, 400), border: "1px solid #e5e7eb", borderRadius: 8 }}>
              <ReactFlow nodes={buildNodes(events)} edges={buildEdges(events)} fitView onNodeClick={(_, node) => handleNodeClick(node)}>
                <Background />
                <MiniMap />
                <Controls />
              </ReactFlow>
            </div>
            {selectedEvent && (
              <div className="info-box" style={{ marginTop: 12 }}>
                <h3>Event Details</h3>
                <pre className="error-body">{JSON.stringify(selectedEvent, null, 2)}</pre>
                <button className="refresh-btn" onClick={() => setSelectedEvent(null)} style={{ marginTop: 8 }}>
                  Close
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {loading && <div className="loading-state">Loading system metrics...</div>}
      {contractError && !loading && (
        <div className="error-state">
          <div style={{ fontWeight: 600 }}>Contract mismatch</div>
          <div className="error-meta">request_id: {contractError.request_id || "n/a"}</div>
          <div className="error-meta">duration_ms: {contractError.duration_ms ?? "n/a"}</div>
          <button className="refresh-btn" style={{ marginTop: 12 }} onClick={fetchSystemData}>
            Retry
          </button>
        </div>
      )}
      {error && !loading && (
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
          <div style={{ fontWeight: 600, marginBottom: "8px" }}>Failed to load system data</div>
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
            onClick={fetchSystemData}
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

      {systemData && !loading && !error && (
        <>
          <div className="metrics-grid-large">
            <MetricCard
              title="Total Users"
              value={systemData.users?.total || 0}
              subtitle={`${systemData.users?.active || 0} active (${systemData.users?.active_percentage || 0}%)`}
              icon="👥"
            />
            <MetricCard
              title="Timeline Refreshes"
              value={systemData.timeline?.refreshes || 0}
              subtitle={`${systemData.timeline?.avg_per_user || 0} per active user`}
              icon="📊"
            />
            <MetricCard title="VSCode Actions" value={systemData.vscode?.total_actions || 0} subtitle="Code edits, commits, etc" icon="💻" />
            <MetricCard
              title="Messages Sent"
              value={systemData.communication?.total_messages || 0}
              subtitle={`${systemData.communication?.total_chats || 0} chats`}
              icon="💬"
            />
            <MetricCard
              title="Notifications"
              value={systemData.notifications?.total || 0}
              subtitle={`${systemData.notifications?.urgent || 0} urgent, ${systemData.notifications?.conflicts || 0} conflicts`}
              icon="🔔"
            />
          </div>

          <div className="section">
            <h2>Daily Activity Trend</h2>
            <div className="activity-chart">
              {dailyActivity.map((day, index) => {
                const total = day.total || 0;
                const actions = day.actions || 0;
                const messages = day.messages || 0;
                const heightPercentage = maxActivity ? (total / maxActivity) * 100 : 0;
                const actionHeight = total ? (actions / total) * 100 : 0;
                const messageHeight = total ? (messages / total) * 100 : 0;

                return (
                  <div key={index} className="chart-bar-container">
                    <div
                      className="chart-bar"
                      style={{ height: `${heightPercentage}%` }}
                      title={`${day.date}: ${total} total (${actions} actions, ${messages} messages)`}
                    >
                      <div className="chart-bar-actions" style={{ height: `${actionHeight}%` }} />
                      <div className="chart-bar-messages" style={{ height: `${messageHeight}%` }} />
                    </div>
                    <div className="chart-label">
                      {day.date
                        ? new Date(day.date).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                        : ""}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="chart-legend">
              <span>
                <span className="legend-box actions"></span> Actions
              </span>
              <span>
                <span className="legend-box messages"></span> Messages
              </span>
            </div>
          </div>

          <div className="section-grid">
            <div className="info-box">
              <h3>Action Types</h3>
              <div className="usage-list">
                {Object.entries(systemData.feature_usage?.action_types || {})
                  .sort((a, b) => b[1] - a[1])
                  .map(([type, count]) => (
                    <div key={type || "unknown"} className="usage-item">
                      <span className="usage-name">{type || "unknown"}</span>
                      <span className="usage-count">{count}</span>
                    </div>
                  ))}
                {Object.keys(systemData.feature_usage?.action_types || {}).length === 0 && (
                  <p className="text-gray-500">No action data</p>
                )}
              </div>
            </div>

            <div className="info-box">
              <h3>Notification Types</h3>
              <div className="usage-list">
                {Object.entries(systemData.notifications?.by_type || {})
                  .sort((a, b) => b[1] - a[1])
                  .map(([type, count]) => (
                    <div key={type} className="usage-item">
                      <span className="usage-name">{type}</span>
                      <span className="usage-count">{count}</span>
                    </div>
                  ))}
                {Object.keys(systemData.notifications?.by_type || {}).length === 0 && (
                  <p className="text-gray-500">No notification data</p>
                )}
              </div>
            </div>
          </div>

          {systemData.vscode?.top_users?.length > 0 && (
            <div className="section">
              <h2>Top VSCode Users</h2>
              <div className="top-users-list">
                {systemData.vscode.top_users.map((user, index) => (
                  <div key={user.email || index} className="top-user-item">
                    <span className="user-rank">#{index + 1}</span>
                    <span className="user-email">{user.email}</span>
                    <span className="user-count">{user.action_count} actions</span>
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

export default SystemOverviewDashboard;
