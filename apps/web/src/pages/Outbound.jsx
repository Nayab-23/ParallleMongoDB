import { useEffect, useState } from "react";
import "./Auth.css";
import { API_BASE_URL } from "../config";

export default function Outbound() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const res = await fetch(`${API_BASE_URL}/api/outbound/summary`, {
          credentials: "include",
        });
        if (!res.ok) throw new Error("Failed to load outbound summary");
        const json = await res.json();
        setData(json);
      } catch (err) {
        console.error("Outbound summary failed", err);
        setError("Could not load outbound summary.");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const renderSection = (title, items = []) => {
    const list = Array.isArray(items) ? items : [];
    return (
      <div style={{ border: "1px solid var(--border)", borderRadius: 12, padding: 12, background: "var(--code-bg)", display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontWeight: 700 }}>{title}</div>
        {list.length === 0 && <div className="roles">No items.</div>}
        {list.map((item, idx) => (
          <div key={idx} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "var(--panel-glass)" }}>
            <div style={{ fontWeight: 600 }}>{item.title || item.account || "Item"}</div>
            {item.detail && <div className="roles" style={{ marginTop: 4 }}>{item.detail}</div>}
            {item.link && (
              <a href={item.link} target="_blank" rel="noreferrer" className="auth-link" style={{ display: "inline-block", marginTop: 6 }}>
                Open
              </a>
            )}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="auth-container">
      <div className="auth-card glass" style={{ width: "100%", maxWidth: 960, textAlign: "left" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h2 className="auth-title">Outbound Intelligence</h2>
            <p className="auth-subtitle">Client analytics and external opportunities.</p>
          </div>
          <button className="auth-button" style={{ width: "auto", padding: "10px 14px" }} onClick={() => window.location.reload()} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {error && <div className="auth-status">{error}</div>}
        {loading && <div className="subhead">Loading outbound…</div>}

        {data && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
            {renderSection("At-risk clients", data.at_risk_clients)}
            {renderSection("Opportunities", data.opportunities)}
            {renderSection("External triggers", data.external_triggers)}
            {renderSection("Sentiment alerts", data.sentiment_alerts)}
          </div>
        )}
      </div>
    </div>
  );
}
