import "./Recommendations.css";

export default function Recommendations({
  recommendations = [],
  onAccept = () => {},
  onDismiss = () => {},
  processingIndex = null,
  showEmptyState = false,
}) {
  if (!Array.isArray(recommendations) || recommendations.length === 0) {
    return showEmptyState ? (
      <div className="recommendations-section">
        <div className="recommendations-header">
          <h3>⚡ New Recommendations</h3>
          <p className="rec-count">0 pending</p>
        </div>
        <div className="rec-empty">No new AI suggestions right now.</div>
      </div>
    ) : null;
  }

  return (
    <div className="recommendations-section">
      <div className="recommendations-header">
        <h3>⚡ New Recommendations</h3>
        <p className="rec-count">
          {recommendations.length} pending
          {recommendations.length > 5 ? " • Scroll to see all" : ""}
        </p>
      </div>

      <div className="recommendations-list">
        {recommendations.map((rec, index) => (
          <div key={index} className="recommendation-card">
            <div className="rec-content">
              <div className="rec-title">{rec.item?.title || "Suggestion"}</div>
              {rec.item?.detail && <div className="rec-detail">{rec.item.detail}</div>}
              {rec.reason && <div className="rec-reason">{rec.reason}</div>}
              <div className="rec-meta">
                {rec.timeframe && <span className="rec-badge timeframe">{rec.timeframe}</span>}
                {rec.section && <span className="rec-badge section">{rec.section}</span>}
                {rec.signature && <span className="rec-badge section">sig:{rec.signature}</span>}
              </div>
            </div>

            <div className="rec-actions">
              <button
                className="rec-btn accept"
                onClick={() => onAccept(index)}
                disabled={processingIndex === index}
                title="Add to your plan"
              >
                {processingIndex === index ? "…" : "✓ Accept"}
              </button>
              <button
                className="rec-btn dismiss"
                onClick={() => onDismiss(index)}
                disabled={processingIndex === index}
                title="Dismiss this suggestion"
              >
                {processingIndex === index ? "…" : "✕ Dismiss"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
