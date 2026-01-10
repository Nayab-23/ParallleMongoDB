import "./Brief.css";

export default function OutboundBrief({ data = {} }) {
  return (
    <div className="brief-grid">
      <BriefSection title="At-risk Clients" items={data.at_risk_clients || data.at_risk} />
      <BriefSection title="Opportunities" items={data.opportunities} />
      <BriefSection title="External Triggers" items={data.external_triggers} />
      <BriefSection title="Sentiment Alerts" items={data.sentiment_alerts} />
    </div>
  );
}

function BriefSection({ title, items }) {
  const list = Array.isArray(items) ? items : [];
  return (
    <div className="brief-card">
      <div className="brief-card-title">{title}</div>
      {list.length === 0 && <div className="brief-empty">No items.</div>}
      {list.map((item, idx) => (
        <div key={idx} className="brief-item">
          <div className="brief-item-title">{item.title || item.account || "Item"}</div>
          {item.detail && <div className="brief-item-sub">{item.detail}</div>}
          {item.snippet && <div className="brief-item-sub">{item.snippet}</div>}
          {item.link && (
            <a
              href={item.link}
              target="_blank"
              rel="noreferrer"
              className="brief-link"
            >
              Open
            </a>
          )}
        </div>
      ))}
    </div>
  );
}
