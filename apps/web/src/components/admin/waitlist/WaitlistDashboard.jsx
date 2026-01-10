import { useEffect, useRef, useState } from "react";
import { getWaitlistSubmissions, getWaitlistStats, deleteWaitlistSubmission, formatAdminError } from "../../../api/adminApi";
import "./WaitlistDashboard.css";

const WaitlistDashboard = () => {
  const [items, setItems] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const [statsError, setStatsError] = useState(null);
  const [lastMeta, setLastMeta] = useState({ request_id: null, duration_ms: null });
  const seqRef = useRef(0);
  const controllerRef = useRef(null);

  useEffect(() => {
    fetchStats();
    fetchPage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchStats = async () => {
    try {
      const resp = await getWaitlistStats();
      if (!resp?.success) {
        setStatsError(resp?.error || { message: "Failed to load stats", request_id: resp?.request_id });
        setStats(null);
        return;
      }
      setStats(resp.data ?? {});
    } catch (err) {
      setStatsError({ message: err?.message || "Failed to load stats" });
      setStats(null);
    }
  };

  const fetchPage = async (cursor = null) => {
    if (controllerRef.current) controllerRef.current.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const seq = ++seqRef.current;
    setLoading(true);
    setError(null);
    try {
      const resp = await getWaitlistSubmissions(50, cursor, { signal: controller.signal });
      if (seq !== seqRef.current) return;
      setLastMeta({ request_id: resp?.request_id, duration_ms: resp?.duration_ms });
      if (!resp?.success) {
        setError({
          message: resp?.error?.message || "Failed to load waitlist",
          status: resp?.status,
          request_id: resp?.request_id,
        });
        setItems([]);
        setNextCursor(null);
        return;
      }
      const payload = resp?.data ?? {};
      const list = Array.isArray(payload.items) ? payload.items : [];
      setItems(list);
      setNextCursor(payload.next_cursor || null);
    } catch (err) {
      if (seq !== seqRef.current) return;
      setError({ message: err?.message || "Failed to load waitlist" });
      setItems([]);
      setNextCursor(null);
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    if (!id) return;
    if (!window.confirm("Delete this submission?")) return;
    const resp = await deleteWaitlistSubmission(id);
    if (!resp?.success) {
      alert(`Delete failed: ${resp?.error?.message || "Unknown error"} (request_id ${resp?.request_id || "n/a"})`);
      return;
    }
    setItems((prev) => prev.filter((x) => x.id !== id));
  };

  const formatDate = (ts) => {
    if (!ts) return "—";
    return new Date(ts).toLocaleString();
  };

  return (
    <div className="waitlist-dashboard">
      <div className="waitlist-header">
        <div>
          <h2>Waitlist Admin</h2>
          <p className="waitlist-subtitle">Manage submissions and stats</p>
        </div>
        <div className="waitlist-actions">
          <div className="waitlist-count">Last request_id: {lastMeta.request_id || "—"}</div>
          <button onClick={() => fetchPage()} className="refresh-btn">
            🔄 Refresh
          </button>
        </div>
      </div>

      {stats && (
        <div className="metrics-grid-large" style={{ marginBottom: 16 }}>
          <div className="metric-card">
            <div className="metric-title">Total</div>
            <div className="metric-value">{stats.total ?? 0}</div>
          </div>
          <div className="metric-card">
            <div className="metric-title">Last 24h</div>
            <div className="metric-value">{stats.last_24h ?? 0}</div>
          </div>
          <div className="metric-card">
            <div className="metric-title">Last 7d</div>
            <div className="metric-value">{stats.last_7d ?? 0}</div>
          </div>
        </div>
      )}
      {statsError && (
        <div className="error-state">
          <div>Failed to load stats</div>
          {statsError.request_id && <div className="error-meta">request_id: {statsError.request_id}</div>}
        </div>
      )}

      {loading && <div className="waitlist-loading">Loading submissions...</div>}
      {error && (
        <div className="waitlist-error">
          <div style={{ fontWeight: 600, marginBottom: 8 }}>Failed to load waitlist</div>
          <pre className="error-body">{formatAdminError(error)}</pre>
          {error.request_id && <div className="error-meta">request_id: {error.request_id}</div>}
        </div>
      )}

      {!loading && !error && items.length === 0 && <div className="empty-state">No submissions</div>}

      {!loading && !error && items.length > 0 && (
        <div className="submissions-list">
          {items.map((sub) => (
            <div key={sub.id} className="submission-card">
              <div className="submission-header">
                <h3>{sub.name || "—"}</h3>
                <span className="submission-date">{formatDate(sub.created_at || sub.submitted_at || sub.timestamp)}</span>
              </div>
              <div className="submission-details">
                <div className="detail-row">
                  <span className="label">Email</span>
                  <a href={`mailto:${sub.email}`} className="detail-value">
                    {sub.email || "—"}
                  </a>
                </div>
                <div className="detail-row">
                  <span className="label">Source</span>
                  <span className="detail-value">{sub.source || "—"}</span>
                </div>
                <div className="detail-row">
                  <span className="label">Notes</span>
                  <span className="detail-value">{sub.notes || sub.metadata || "—"}</span>
                </div>
                <div className="detail-row">
                  <span className="label">ID</span>
                  <span className="detail-value">{sub.id}</span>
                </div>
              </div>
              <button className="btn-delete-room" onClick={() => handleDelete(sub.id)}>
                Delete
              </button>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        <button className="refresh-btn" disabled={!nextCursor} onClick={() => fetchPage(nextCursor)}>
          Next page
        </button>
        <button className="refresh-btn" onClick={() => fetchPage()}>
          Reset
        </button>
      </div>
    </div>
  );
};

export default WaitlistDashboard;
