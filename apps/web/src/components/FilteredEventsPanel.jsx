import { useEffect, useState } from "react";
import "./FilteredEventsPanel.css";
import { API_BASE_URL } from "../config";

export default function FilteredEventsPanel() {
  const [filteredEvents, setFilteredEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState({});

  const loadFilteredEvents = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/brief/filtered-events`, {
        credentials: "include",
      });
      if (!res.ok) {
        throw new Error(`Failed to fetch filtered events: ${res.status}`);
      }
      const data = await res.json();
      setFilteredEvents(data.filtered_events || []);
    } catch (err) {
      console.error("[FilteredEventsPanel] Failed to load:", err);
      setError("Failed to load filtered events");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadFilteredEvents();
  }, []);

  const handleShowAgain = async (signature) => {
    setBusy((prev) => ({ ...prev, [signature]: true }));
    try {
      const res = await fetch(`${API_BASE_URL}/api/brief/unfilter-event`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signature }),
      });

      if (!res.ok) {
        throw new Error(`Failed to unfilter event: ${res.status}`);
      }

      // Remove from local state
      setFilteredEvents((prev) => prev.filter((e) => e.signature !== signature));
    } catch (err) {
      console.error("[FilteredEventsPanel] Failed to unfilter:", err);
      alert("Failed to restore event. Please try again.");
    } finally {
      setBusy((prev) => {
        const next = { ...prev };
        delete next[signature];
        return next;
      });
    }
  };

  if (loading) {
    return (
      <div className="filtered-events-panel">
        <div className="panel-header">
          <h3>Filtered Recurring Events</h3>
          <p className="panel-subtitle">Auto-hidden events based on patterns</p>
        </div>
        <div className="panel-loading">Loading filtered events...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="filtered-events-panel">
        <div className="panel-header">
          <h3>Filtered Recurring Events</h3>
          <p className="panel-subtitle">Auto-hidden events based on patterns</p>
        </div>
        <div className="panel-error">
          <p>{error}</p>
          <button onClick={loadFilteredEvents} className="retry-btn">
            🔄 Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="filtered-events-panel">
      <div className="panel-header">
        <h3>Filtered Recurring Events</h3>
        <p className="panel-subtitle">
          Auto-hidden events based on recurring patterns ({filteredEvents.length})
        </p>
      </div>

      {filteredEvents.length === 0 ? (
        <div className="empty-state">
          <p>No filtered events yet</p>
          <p className="empty-subtitle">
            Recurring events that match patterns will be auto-hidden and appear here
          </p>
        </div>
      ) : (
        <div className="filtered-events-list">
          {filteredEvents.map((event) => (
            <div key={event.signature} className="filtered-event-item">
              <div className="event-content">
                <div className="event-title">{event.title || "Untitled Event"}</div>
                <div className="event-meta">
                  <span className="event-source">{event.source || "Unknown source"}</span>
                  {event.deletion_count > 0 && (
                    <span className="deletion-badge">
                      🗑️ Deleted {event.deletion_count} time{event.deletion_count === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
                {event.pattern && (
                  <div className="event-pattern">Pattern: {event.pattern}</div>
                )}
              </div>
              <button
                className="show-again-btn"
                disabled={busy[event.signature]}
                onClick={() => handleShowAgain(event.signature)}
              >
                {busy[event.signature] ? "Restoring..." : "Show Again"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
