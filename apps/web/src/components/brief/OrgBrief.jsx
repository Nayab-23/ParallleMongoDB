import "./Brief.css";

export default function OrgBrief({ data = {} }) {
  return (
    <div className="brief-grid">
      <BriefSection title="Top Organizational Risks" items={data.risks || data.fires} />
      <BriefSection title="Department / Room Statuses" items={data.statuses} />
      <BriefSection title="Bottlenecks" items={data.bottlenecks} />
      <BriefSection title="Org Activity Summary" items={data.activity} />
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
          <div className="brief-item-title">{item.title || item.name || "Item"}</div>
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
