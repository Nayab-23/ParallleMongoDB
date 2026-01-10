import { useEffect, useRef, useState } from "react";
import "./HistoryPanel.css";
import { fetchBriefHistory } from "../../lib/tasksApi";

export default function HistoryPanel({ refreshToken = 0 }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const listRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchBriefHistory({ action: "all", limit: 100 });
        if (cancelled) return;
        setItems(data?.items || data || []);
      } catch (err) {
        if (!cancelled) {
          console.error("Failed to fetch history:", err);
          setError("Failed to load history");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [refreshToken]);

  const renderItem = (item) => {
    const isCompleted = item.action === "completed";
    return (
      <div key={item.id || item.title} className="history-item">
        <div className="item-icon" style={{ background: isCompleted ? "#10b981" : "#ef4444" }}>
          {isCompleted ? "✓" : "✕"}
        </div>
        <div className="item-content">
          <div className="item-title">{item.title || "Untitled"}</div>
          {item.description && <div className="item-detail">{item.description}</div>}
          <div className="item-meta">
            {item.section && <span>{item.section}</span>}
            {item.timeframe && <span style={{ marginLeft: 8 }}>{item.timeframe}</span>}
            {item.created_at && (
              <span style={{ marginLeft: 8 }}>
                {new Date(item.created_at).toLocaleString()}
              </span>
            )}
          </div>
        </div>
      </div>
    );
  };

  const scrollList = (delta) => {
    if (!listRef.current) return;
    listRef.current.scrollBy({ top: delta, behavior: "smooth" });
  };

  return (
    <div className="history-panel">
      <div className="panel-header">
        <h3>Activity History</h3>
        <p className="panel-subtitle">Completed & deleted items</p>
      </div>

      {loading ? (
        <div className="panel-loading">Loading history...</div>
      ) : error ? (
        <div className="panel-loading">{error}</div>
      ) : (
        <div className="history-scroll-shell">
          <button className="history-scroll-btn" onClick={() => scrollList(-200)} aria-label="Scroll up">
            ↑
          </button>
          <div
            className="history-list"
            ref={listRef}
          >
            {items.length === 0 ? (
              <div className="empty-state">
                <p>No activity yet</p>
                <p className="empty-subtitle">Completed and deleted items will appear here</p>
              </div>
            ) : (
              items.map(renderItem)
            )}
          </div>
          <button className="history-scroll-btn" onClick={() => scrollList(200)} aria-label="Scroll down">
            ↓
          </button>
        </div>
      )}
    </div>
  );
}
