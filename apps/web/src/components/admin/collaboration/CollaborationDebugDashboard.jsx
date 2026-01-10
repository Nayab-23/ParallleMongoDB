import React, { useEffect, useRef, useState, useCallback } from "react";
import {
  getCollaborationDebug,
  formatAdminError,
  getCollaborationMessages,
  getCollaborationGraph,
  runCollaborationAudit,
} from "../../../api/adminApi";
import MultiUserSelector from "../MultiUserSelector";
import MetricCard from "../shared/MetricCard";
import InteractionGraph from "./InteractionGraph";
import ReactFlow, { Background, Controls, MiniMap } from "reactflow";
import "reactflow/dist/style.css";
import "./Collaboration.css";

const CollaborationDebugDashboard = () => {
  const [selectedUsers, setSelectedUsers] = useState([]);
  const [days, setDays] = useState(7);
  const [collabData, setCollabData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [contractError, setContractError] = useState(null);
  const [legacyInfo, setLegacyInfo] = useState(null);
  const [lastMeta, setLastMeta] = useState({ request_id: null, duration_ms: null });
  const [debugInfo, setDebugInfo] = useState(null);
  const [historyDepth, setHistoryDepth] = useState(20);
  const [liveOnly, setLiveOnly] = useState(true);
  const [messagesByUser, setMessagesByUser] = useState({});
  const [messagesError, setMessagesError] = useState(null);
  const controllerRef = useRef(null);
  const seqRef = useRef(0);

  const [activeTab, setActiveTab] = useState("summary");
  const [graphData, setGraphData] = useState(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState(null);
  const graphControllerRef = useRef(null);
  const graphSeqRef = useRef(0);
  const [selectedGraphNode, setSelectedGraphNode] = useState(null);
  const [selectedThread, setSelectedThread] = useState(null);
  const [selectedSignal, setSelectedSignal] = useState(null);

  const [auditResult, setAuditResult] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState(null);
  const threads = Array.isArray(graphData?.threads) ? graphData.threads : [];
  const signals = Array.isArray(graphData?.signals) ? graphData.signals : [];

  useEffect(() => {
    if (!selectedThread && threads.length > 0) {
      setSelectedThread(threads[0]);
    }
  }, [threads, selectedThread]);

  useEffect(() => {
    if (selectedUsers.length > 0) {
      fetchCollabData();
      if (activeTab === "graph") {
        fetchGraphData();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedUsers, days, activeTab]);

  useEffect(() => {
    if (!selectedUsers.length || liveOnly) return;
    fetchMessagesForUsers();
  }, [selectedUsers, historyDepth, liveOnly]);

  const fetchCollabData = async () => {
    if (controllerRef.current) controllerRef.current.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const seq = ++seqRef.current;
    setLoading(true);
    setError(null);
    setContractError(null);

    try {
      const resp = await getCollaborationDebug(selectedUsers, days, { signal: controller.signal });
      if (seq !== seqRef.current) return;
      setLegacyInfo(resp?.debug?.legacy ? { request_id: resp?.request_id, status: resp?.status, endpoint: resp?.debug?.url } : null);
      setLastMeta({ request_id: resp?.request_id, duration_ms: resp?.duration_ms });
      setDebugInfo(resp?.debug || null);
      if (!resp?.success) {
        setError({
          message: resp?.error?.message || "Failed to load collaboration data",
          details: resp?.error?.details || resp?.error,
          status: resp?.status,
          request_id: resp?.request_id,
        });
        setCollabData(null);
        return;
      }
      const payload = resp?.data ?? {};
      const requiredOk = Array.isArray(payload.users) && payload.date_range && payload.summary;
      if (!requiredOk) {
        setContractError({
          message: "Contract mismatch",
          request_id: resp?.request_id,
          duration_ms: resp?.duration_ms,
        });
        setCollabData(null);
        return;
      }
      const normalized = {
        ...payload,
        summary: payload.summary ?? {},
        chat_interactions: Array.isArray(payload.chat_interactions) ? payload.chat_interactions : [],
        notifications: Array.isArray(payload.notifications) ? payload.notifications : [],
        conflicts_detected: Array.isArray(payload.conflicts_detected) ? payload.conflicts_detected : [],
        interaction_graph: {
          nodes: Array.isArray(payload?.interaction_graph?.nodes) ? payload.interaction_graph.nodes : [],
          edges: Array.isArray(payload?.interaction_graph?.edges) ? payload.interaction_graph.edges : [],
        },
        collaboration_opportunities: Array.isArray(payload.collaboration_opportunities) ? payload.collaboration_opportunities : [],
      };
      setCollabData(normalized);
    } catch (err) {
      if (seq !== seqRef.current) return;
      setError({ message: err?.message || "Failed to load collaboration data", status: err?.status });
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  };

  const fetchMessagesForUsers = async () => {
    setMessagesError(null);
    const results = {};
    for (const email of selectedUsers) {
      try {
        const data = await getCollaborationMessages(email, historyDepth);
        results[email] = Array.isArray(data?.messages) ? data.messages : Array.isArray(data) ? data : [];
      } catch (err) {
        setMessagesError(err);
        results[email] = [];
      }
    }
    setMessagesByUser(results);
  };

  const fetchGraphData = async () => {
    if (!selectedUsers.length) return;
    if (graphControllerRef.current) graphControllerRef.current.abort();
    const controller = new AbortController();
    graphControllerRef.current = controller;
    const seq = ++graphSeqRef.current;
    setGraphLoading(true);
    setGraphError(null);
    setAuditResult(null);
    try {
      const resp = await getCollaborationGraph(selectedUsers, days, 50, true, { signal: controller.signal });
      if (seq !== graphSeqRef.current) return;
      if (!resp?.success) {
        setGraphError({
          message: resp?.error?.message || "Failed to load collaboration graph",
          status: resp?.status,
          request_id: resp?.request_id,
          details: resp?.error?.details || resp?.error,
        });
        setGraphData(null);
        return;
      }
      const payload = resp?.data ?? {};
      const requiredOk =
        Array.isArray(payload.users) &&
        payload.date_range &&
        Array.isArray(payload.nodes) &&
        Array.isArray(payload.edges) &&
        Array.isArray(payload.threads) &&
        Array.isArray(payload.signals);
      if (!requiredOk) {
        setGraphError({
          message: "Contract mismatch",
          request_id: resp?.request_id,
          status: resp?.status,
        });
        setGraphData(null);
        return;
      }
      setGraphData(payload);
    } catch (err) {
      if (seq !== graphSeqRef.current) return;
      setGraphError({ message: err?.message || "Failed to load collaboration graph" });
      setGraphData(null);
    } finally {
      if (seq === graphSeqRef.current) setGraphLoading(false);
    }
  };

  const runAudit = async () => {
    setAuditLoading(true);
    setAuditError(null);
    setAuditResult(null);
    try {
      const resp = await runCollaborationAudit({ users: selectedUsers, days, persist: true });
      if (!resp?.success) {
        setAuditError({
          message: resp?.error?.message || "Audit failed",
          status: resp?.status,
          request_id: resp?.request_id,
        });
        return;
      }
      setAuditResult(resp?.data ?? {});
    } catch (err) {
      setAuditError({ message: err?.message || "Audit failed" });
    } finally {
      setAuditLoading(false);
    }
  };

  const renderGraphInspector = () => {
    if (selectedThread) {
      return (
        <div style={{ marginBottom: 12 }}>
          <div className="section-label">Thread {selectedThread.chat_id}</div>
          <div className="error-meta">Messages: {selectedThread.message_count}</div>
          <div className="error-meta">Last activity: {selectedThread.last_activity}</div>
          <div className="stage-items" style={{ maxHeight: 240, overflow: "auto" }}>
            {(selectedThread.messages || []).map((m) => (
              <div key={m.id} className="stage-item-row">
                <div className="stage-item-main">
                  <div className="stage-item-title">
                    {m.role}: {m.text_preview || "(no text)"}
                  </div>
                  <div className="stage-item-meta">
                    <span>{m.from_email || ""}</span>
                    <span>{m.ts || ""}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      );
    }
    if (selectedSignal) {
      return (
        <div>
          <div className="section-label">Signal {selectedSignal.computed_hash}</div>
          <div className="error-meta">expected_send: {String(selectedSignal.expected_send)}</div>
          <div className="error-meta">actually_sent: {String(selectedSignal.actually_sent)}</div>
          <div className="error-meta">notification_id: {selectedSignal.notification_id || "n/a"}</div>
        </div>
      );
    }
    if (selectedGraphNode) {
      return (
        <div>
          <div className="section-label">Node {selectedGraphNode.id}</div>
          <div className="error-meta">type: {selectedGraphNode.data?.type || "n/a"}</div>
        </div>
      );
    }
    return <div className="empty-state">Select a node</div>;
  };

  return (
    <div className="collaboration-debug-dashboard">
      <div className="debug-controls" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div className="error-meta">last request_id: {lastMeta.request_id || "—"}</div>
          <div className="error-meta">duration_ms: {lastMeta.duration_ms ?? "—"}</div>
          <a href="/api/admin/_health" target="_blank" rel="noreferrer" className="error-meta">
            /api/admin/_health
          </a>
          <a href="/api/admin/_routes" target="_blank" rel="noreferrer" className="error-meta">
            /api/admin/_routes
          </a>
        </div>
      </div>

      {debugInfo && (
        <div className="info-box" style={{ margin: "8px 0", padding: "12px" }}>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>Debug snapshot</div>
          <div className="error-meta">cutoff_timestamp: {String(debugInfo.cutoff_timestamp ?? "n/a")}</div>
          <div className="error-meta">messages_found_count: {String(debugInfo.messages_found_count ?? "n/a")}</div>
          <div className="error-meta">chats_found_count: {String(debugInfo.chats_found_count ?? "n/a")}</div>
        </div>
      )}

      {legacyInfo && (
        <div className="error-state" style={{ marginTop: 8 }}>
          <div style={{ fontWeight: 600 }}>Non-enveloped admin response</div>
          <div className="error-meta">endpoint: {legacyInfo.endpoint}</div>
          <div className="error-meta">request_id: {legacyInfo.request_id || "n/a"}</div>
          <div className="error-meta">status: {legacyInfo.status ?? "n/a"}</div>
        </div>
      )}

      <div className="admin-tabs" style={{ marginTop: 12 }}>
        {[
          { id: "summary", label: "Summary" },
          { id: "graph", label: "Graph" },
        ].map((tab) => (
          <button key={tab.id} className={`admin-tab ${activeTab === tab.id ? "active" : ""}`} onClick={() => setActiveTab(tab.id)}>
            {tab.label}
          </button>
        ))}
      </div>

      <div className="debug-controls">
        <MultiUserSelector selected={selectedUsers} onChange={setSelectedUsers} max={4} placeholder="Select 1-4 users to analyze..." />

        {selectedUsers.length > 0 && (
          <div className="days-selector">
            <label>Last</label>
            <select
              value={days}
              onChange={(e) => {
                const newDays = parseInt(e.target.value, 10);
                setDays(newDays);
              }}
              className="days-select"
            >
              <option value={1}>1 day</option>
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
            </select>
          </div>
        )}

        {selectedUsers.length > 0 && (
          <>
            <div className="days-selector">
              <label>History depth</label>
              <select value={historyDepth} onChange={(e) => setHistoryDepth(parseInt(e.target.value, 10))} className="days-select">
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
            <label className="auto-refresh-toggle">
              <input type="checkbox" checked={liveOnly} onChange={(e) => setLiveOnly(e.target.checked)} />
              <span>Live only</span>
            </label>
          </>
        )}
      </div>

      {activeTab === "summary" && error && (
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
          <div style={{ fontWeight: 600, marginBottom: "8px" }}>Failed to load collaboration data</div>
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
              <summary style={{ cursor: "pointer", fontWeight: 500 }}>Error Details (HTTP {error.status})</summary>
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
            onClick={fetchCollabData}
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

      {activeTab === "summary" && loading && <div className="loading-state">Loading collaboration data...</div>}
      {activeTab === "graph" && graphLoading && <div className="loading-state">Loading collaboration graph...</div>}

      {selectedUsers.length === 0 && !loading && !graphLoading && (
        <div className="empty-state">
          <p>Select 1-4 users to analyze their collaboration patterns</p>
        </div>
      )}

      {activeTab === "summary" && collabData && !loading && !error && (
        <>
          <div className="metrics-grid">
            <MetricCard
              title="Chat Interactions"
              value={collabData.summary?.total_chats || 0}
              subtitle={`${collabData.summary?.total_messages || 0} messages`}
              icon="💬"
            />
            <MetricCard
              title="Notifications"
              value={collabData.summary?.total_notifications || 0}
              subtitle="Between selected users"
              icon="🔔"
            />
            <MetricCard title="Conflicts" value={collabData.summary?.total_conflicts || 0} subtitle="File + Semantic" icon="⚠️" />
            <MetricCard
              title="Opportunities"
              value={collabData.summary?.total_opportunities || 0}
              subtitle="Collaboration suggestions"
              icon="🤝"
            />
          </div>

          {collabData.interaction_graph && (
            <div className="section">
              <h2>Interaction Graph</h2>
              <InteractionGraph data={collabData.interaction_graph} />
            </div>
          )}

          {collabData.chat_interactions?.length > 0 && (
            <div className="section">
              <h2>Chat Interactions ({collabData.chat_interactions.length})</h2>
              <div className="chats-grid">
                {collabData.chat_interactions.map((chat, index) => (
                  <div key={index} className="chat-box">
                    <div className="chat-header">
                      <span className="chat-participants">{chat.participants.join(", ")}</span>
                      <span className="chat-count">{chat.message_count} msgs</span>
                    </div>
                    <div className="chat-time">Last active: {new Date(chat.last_activity).toLocaleString()}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {collabData.notifications?.length > 0 && (
            <div className="section">
              <h2>Notification Feed ({collabData.notifications.length})</h2>
              <div className="notifications-feed">
                {collabData.notifications.slice(0, 20).map((notif, index) => (
                  <div key={index} className={`notification-item ${notif.severity}`}>
                    <div className="notification-header">
                      <span className={`notification-type ${notif.severity}`}>
                        {notif.severity === "urgent" ? "🔴" : "🔵"} {notif.type}
                      </span>
                      <span className="notification-time">{new Date(notif.timestamp).toLocaleString()}</span>
                    </div>
                    <div className="notification-flow">
                      {notif.from_user && (
                        <>
                          <span className="notification-user">{notif.from_user}</span>
                          <span className="notification-arrow">→</span>
                        </>
                      )}
                      <span className="notification-user">{notif.to_user}</span>
                    </div>
                    <div className="notification-title">{notif.title}</div>
                    <div className="notification-message">{notif.message}</div>
                    {notif.read ? <span className="notification-status read">✅ Read</span> : <span className="notification-status unread">📬 Unread</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {!liveOnly && selectedUsers.length > 0 && (
            <div className="section">
              <h2>Recent Messages (last {historyDepth})</h2>
              {messagesError && (
                <div className="error-state">
                  {messagesError.status === 404 ? "Not available (backend not deployed)" : messagesError.message || "Failed to load messages"}
                </div>
              )}
              <div className="chats-grid">
                {selectedUsers.map((email) => (
                  <div key={email} className="chat-box" style={{ maxHeight: 260, overflowY: "auto" }}>
                    <div className="chat-header">
                      <span className="chat-participants">{email}</span>
                      <span className="chat-count">{messagesByUser[email]?.length || 0} msgs</span>
                    </div>
                    {(messagesByUser[email] || []).map((msg, idx) => (
                      <div key={idx} className="notification-message" style={{ marginBottom: 6 }}>
                        <div className="chat-time">{msg.timestamp ? new Date(msg.timestamp).toLocaleString() : ""}</div>
                        <div>{msg.text || msg.message || JSON.stringify(msg)}</div>
                      </div>
                    ))}
                    {(messagesByUser[email] || []).length === 0 && <div className="text-gray-500">No history</div>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {collabData.conflicts_detected?.length > 0 && (
            <div className="section">
              <h2>Conflicts Detected ({collabData.conflicts_detected.length})</h2>
              <div className="conflicts-grid">
                {collabData.conflicts_detected.map((conflict, index) => (
                  <div key={index} className="conflict-card">
                    <div className="conflict-type-badge">{conflict.type === "file" ? "📄 File Conflict" : "🔍 Semantic Conflict"}</div>
                    <div className="conflict-users">{conflict.users.join(" ↔ ")}</div>
                    <div className="conflict-title">{conflict.title}</div>
                    {conflict.file && <div className="conflict-file">File: {conflict.file}</div>}
                    {conflict.similarity && <div className="conflict-similarity">Similarity: {Math.round(conflict.similarity * 100)}%</div>}
                    <div className="conflict-time">{new Date(conflict.timestamp).toLocaleString()}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {collabData.collaboration_opportunities?.length > 0 && (
            <div className="section">
              <h2>Collaboration Opportunities ({collabData.collaboration_opportunities.length})</h2>
              <div className="opportunities-list">
                {collabData.collaboration_opportunities.map((opp, index) => (
                  <div key={index} className="opportunity-card">
                    <div className="opportunity-header">
                      <span className="opportunity-icon">🤝</span>
                      <span className="opportunity-score">{Math.round(opp.similarity_score * 100)}% match</span>
                    </div>
                    <div className="opportunity-users">
                      {opp.user1} ↔ {opp.user2}
                    </div>
                    <div className="opportunity-details">
                      <div>
                        {opp.user1}: {opp.user1_activity}
                      </div>
                      <div>
                        {opp.user2}: {opp.user2_activity}
                      </div>
                    </div>
                    <div className="opportunity-suggestion">💡 {opp.suggestion}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {activeTab === "graph" && selectedUsers.length > 0 && (
        <div className="section">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h2>Collaboration Graph</h2>
            <button className="refresh-btn" onClick={fetchGraphData} disabled={graphLoading}>
              {graphLoading ? "Loading..." : "Refresh Graph"}
            </button>
          </div>
          {graphError && (
            <div className="error-state">
              <div style={{ fontWeight: 600 }}>Failed to load graph</div>
              <div>{graphError.message || "Unknown error"}</div>
              {graphError.request_id && <div className="error-meta">request_id: {graphError.request_id}</div>}
            </div>
          )}
          {!graphError && !graphLoading && graphData && (
            <>
              <div className="graph-shell" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "12px" }}>
                <div style={{ height: 520, border: "1px solid #e5e7eb", borderRadius: 8 }}>
                  <ReactFlow
                    nodes={(graphData.nodes || []).map((n) => ({
                      id: n.id,
                      data: { label: n.label || n.id, type: n.type, meta: n.meta },
                      position: { x: n.x || Math.random() * 200, y: n.y || Math.random() * 200 },
                    }))}
                    edges={(graphData.edges || []).map((e) => ({
                      id: e.id || `${e.source}-${e.target}`,
                      source: e.source,
                      target: e.target,
                      label: e.type,
                    }))}
                    onNodeClick={(_, node) => {
                      setSelectedGraphNode(node);
                      const thread = threads.find((t) => t.chat_id === node.id);
                      setSelectedThread(thread || null);
                      const signal = signals.find(
                        (s) => s.computed_hash === node.id || s.chat_id === node.id
                      );
                      setSelectedSignal(signal || null);
                    }}
                    fitView
                  >
                    <Background />
                    <MiniMap />
                    <Controls />
                  </ReactFlow>
                </div>
                <div className="info-box" style={{ maxHeight: 520, overflow: "auto" }}>{renderGraphInspector()}</div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1.2fr 2fr", gap: 12, marginTop: 16 }}>
                <div className="info-box" style={{ maxHeight: 320, overflow: "auto" }}>
                  <div style={{ fontWeight: 700, marginBottom: 8 }}>Threads ({threads.length})</div>
                  {threads.length === 0 && <div className="text-gray-500">No threads found</div>}
                  {threads.map((t) => (
                    <div
                      key={t.chat_id}
                      className={`stage-item-row ${selectedThread?.chat_id === t.chat_id ? "selected" : ""}`}
                      onClick={() => {
                        setSelectedThread(t);
                        setSelectedSignal(null);
                      }}
                      style={{ cursor: "pointer" }}
                    >
                      <div className="stage-item-main">
                        <div className="stage-item-title">{t.participants?.join(", ") || t.chat_id}</div>
                        <div className="stage-item-meta">
                          <span>{t.message_count} msgs</span>
                          <span>{t.last_activity}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="info-box" style={{ maxHeight: 320, overflow: "auto" }}>
                  <div style={{ fontWeight: 700, marginBottom: 8 }}>Message Cascade</div>
                  {selectedThread && Array.isArray(selectedThread.messages) && selectedThread.messages.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {selectedThread.messages.map((m) => (
                        <div key={m.id} className="stage-item-row">
                          <div className="stage-item-main">
                            <div className="stage-item-title">
                              {m.role}: {m.text_preview || "(no text)"}
                            </div>
                            <div className="stage-item-meta">
                              <span>{m.from_email || ""}</span>
                              <span>{m.ts || ""}</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-gray-500">Select a thread to view cascade (works even if graph edges are empty)</div>
                  )}
                </div>
              </div>

              <div className="section" style={{ marginTop: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <h3>Signals ({signals.length})</h3>
                  <button className="refresh-btn" onClick={() => setSelectedSignal(null)}>
                    Clear selection
                  </button>
                </div>
                {signals.length === 0 ? (
                  <div className="empty-state">No signals found</div>
                ) : (
                  <div className="chats-grid">
                    {signals.map((s) => (
                      <div
                        key={s.computed_hash}
                        className="chat-box"
                        onClick={() => setSelectedSignal(s)}
                        style={{ cursor: "pointer" }}
                      >
                        <div className="chat-header">
                          <span className="chat-participants">{s.type}</span>
                          <span className="chat-count">{s.score ?? ""}</span>
                        </div>
                        <div className="chat-time">expected_send: {String(s.expected_send)}</div>
                        <div className="chat-time">actually_sent: {String(s.actually_sent)}</div>
                        <div className="chat-time">notification_id: {s.notification_id || "n/a"}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
          <div style={{ marginTop: 16 }}>
            <button className="refresh-btn" onClick={runAudit} disabled={auditLoading}>
              {auditLoading ? "Running audit..." : "Run Audit (persist)"}
            </button>
            {auditError && (
              <div className="error-state" style={{ marginTop: 8 }}>
                <div>{auditError.message || "Audit failed"}</div>
                {auditError.request_id && <div className="error-meta">request_id: {auditError.request_id}</div>}
              </div>
            )}
            {auditResult && (
              <div className="info-box" style={{ marginTop: 8 }}>
                <div>run_id: {auditResult.run_id || "n/a"}</div>
                <div>signals_computed: {auditResult.signals_computed ?? auditResult.computed_signals_count ?? "n/a"}</div>
                <div>signals_saved: {auditResult.signals_saved ?? auditResult.persisted_signals_count ?? "n/a"}</div>
                <div>notifications_matched: {auditResult.notifications_matched ?? auditResult.notifications_matched_count ?? "n/a"}</div>
                {Array.isArray(auditResult.sample_mismatches || auditResult.mismatches) &&
                  (auditResult.sample_mismatches || auditResult.mismatches).length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <div className="section-label">Mismatches</div>
                      <div className="stage-items" style={{ maxHeight: 240, overflow: "auto" }}>
                        {(auditResult.sample_mismatches || auditResult.mismatches).map((m, idx) => (
                          <div key={idx} className="stage-item-row">
                            <div className="stage-item-main">
                              <div className="stage-item-title">{m.computed_hash}</div>
                              <div className="stage-item-meta">
                                <span>expected_send: {String(m.expected_send)}</span>
                                <span>actually_sent: {String(m.actually_sent)}</span>
                              </div>
                              {m.matched_notification_id && (
                                <div className="stage-item-reason">notification_id: {m.matched_notification_id}</div>
                              )}
                            </div>
                            <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                              <button className="refresh-btn" onClick={() => navigator.clipboard?.writeText(m.computed_hash || "")}>
                                Copy hash
                              </button>
                              <button
                                className="refresh-btn"
                                onClick={() => {
                                  if (!graphData) return;
                                  const sig = (graphData.signals || []).find((s) => s.computed_hash === m.computed_hash);
                                  setSelectedSignal(sig || null);
                                }}
                              >
                                Highlight
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default CollaborationDebugDashboard;
