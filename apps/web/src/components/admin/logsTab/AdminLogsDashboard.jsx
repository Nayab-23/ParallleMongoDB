import React, { useEffect, useMemo, useRef, useState } from "react";
import { getAdminLogs, writeTestLog } from "../../../api/adminApi";
import "../AdminDashboard.css";
import "./Logs.css";

const SOURCES = [
  { id: "timeline", label: "Timeline" },
  { id: "admin", label: "Admin" },
  { id: "auth", label: "Auth" },
  { id: "request", label: "Request" },
  { id: "all", label: "All" },
];

const LIMITS = [100, 200, 500];
const AUTO_INTERVALS = [
  { id: 0, label: "Off" },
  { id: 5, label: "5s" },
  { id: 15, label: "15s" },
  { id: 30, label: "30s" },
  { id: 60, label: "60s" },
];

const AdminLogsDashboard = () => {
  const [source, setSource] = useState("timeline");
  const [limit, setLimit] = useState(200);
  const [autoInterval, setAutoInterval] = useState(0);
  const [logsData, setLogsData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastFetched, setLastFetched] = useState(null);
  const [writingTest, setWritingTest] = useState(false);
  const [supportedSources, setSupportedSources] = useState(SOURCES.map((s) => s.id));
  const [slowNotice, setSlowNotice] = useState(false);
  const abortRef = useRef(null);

  const entries = useMemo(() => {
    if (!logsData) return [];
    if (Array.isArray(logsData.logs)) return logsData.logs;
    if (Array.isArray(logsData.entries)) return logsData.entries;
    if (Array.isArray(logsData)) return logsData;
    return [];
  }, [logsData]);

  const sortedEntries = useMemo(() => {
    return [...entries].sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0));
  }, [entries]);

  useEffect(() => {
    loadLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, limit]);

  useEffect(() => {
    if (!autoInterval) return undefined;
    const id = setInterval(() => {
      loadLogs({ silent: true });
    }, autoInterval * 1000);
    return () => clearInterval(id);
  }, [autoInterval, source, limit]);

  const loadLogs = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    setError(null);
    setSlowNotice(false);
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const timeoutId = setTimeout(() => setSlowNotice(true), 10000);
    try {
      let data;
      try {
        data = await getAdminLogs(source, limit, { signal: controller.signal });
      } catch (err) {
        if (err?.status === 422 || err?.status === 404) {
          // Fallback: try without source param
          try {
            data = await getAdminLogs(undefined, limit, { signal: controller.signal });
            // Mark this source unsupported
            setSupportedSources((prev) => prev.filter((s) => s !== source));
          } catch (fallbackErr) {
            throw fallbackErr;
          }
        } else {
          throw err;
        }
      }
      setLogsData(data);
      setLastFetched(new Date());
    } catch (err) {
      setError(err);
    } finally {
      clearTimeout(timeoutId);
      if (abortRef.current === controller) abortRef.current = null;
      if (!silent) setLoading(false);
    }
  };

  const handleWriteTest = async () => {
    setWritingTest(true);
    setError(null);
    try {
      await writeTestLog();
      await loadLogs();
    } catch (err) {
      setError(err);
    } finally {
      setWritingTest(false);
    }
  };

  return (
    <div className="logs-dashboard">
      <div className="debug-controls">
        <div className="control-group">
          <label className="control-label">Source</label>
          <select value={source} onChange={(e) => setSource(e.target.value)} className="control-select">
            {SOURCES.filter((opt) => supportedSources.includes(opt.id)).map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label className="control-label">Limit</label>
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="control-select">
            {LIMITS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <label className="control-label">Auto-refresh</label>
          <select
            value={autoInterval}
            onChange={(e) => setAutoInterval(Number(e.target.value))}
            className="control-select"
          >
            {AUTO_INTERVALS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <button className="refresh-btn" onClick={() => loadLogs()} disabled={loading}>
          {loading ? "Loading..." : "Refresh"}
        </button>

        <button className="refresh-btn" onClick={handleWriteTest} disabled={writingTest} style={{ background: "#4b5563" }}>
          {writingTest ? "Writing..." : "Write test log"}
        </button>

        {lastFetched && <span className="last-fetched">Updated {lastFetched.toLocaleTimeString()}</span>}
      </div>

      {error && (
        <div className="error-state">
          <div style={{ fontWeight: 600 }}>Failed to load logs</div>
          <div className="error-meta">
            Status: {error.status || "unknown"} {error.status === 500 ? "(Backend error - check server logs)" : ""}
          </div>
          <div style={{ marginTop: 4 }}>
            {error.status === 404 ? "Not available (backend not deployed)" : error.message || "Unknown error"}
          </div>
          {error.body && <pre className="error-body">{JSON.stringify(error.body, null, 2)}</pre>}
          <button className="retry-btn" onClick={() => loadLogs()}>
            Retry
          </button>
        </div>
      )}

      {loading && !entries.length && <div className="loading-state">Loading logs...</div>}
      {slowNotice && !error && <div className="error-meta">Taking longer than expected…</div>}

      {!loading && !error && sortedEntries.length === 0 && (
        <div className="empty-state">
          No logs found yet. Try "Write test log" or trigger a timeline refresh.
        </div>
      )}

      {!loading && !error && sortedEntries.length > 0 && (
        <div className="logs-list">
          {sortedEntries.map((log, idx) => {
            const level = (log.level || "info").toLowerCase();
            const timestamp = log.timestamp ? new Date(log.timestamp).toLocaleString() : "";
            const context = log.context || log.meta || null;
            return (
              <div key={log.id || `${log.timestamp || "t"}-${idx}`} className="log-entry">
                <div className="log-entry-header">
                  <span className="log-timestamp">{timestamp}</span>
                  <span className={`log-level ${level}`}>{level}</span>
                </div>
                <div className="log-message">{log.message || log.text || "(no message)"}</div>
                {context && (
                  <details className="log-context">
                    <summary>Context</summary>
                    <pre>{JSON.stringify(context, null, 2)}</pre>
                  </details>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default AdminLogsDashboard;
