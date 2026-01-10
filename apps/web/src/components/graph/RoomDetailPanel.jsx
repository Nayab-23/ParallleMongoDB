export default function RoomDetailPanel({ room, onClose, upstream = [], downstream = [] }) {
  return (
    <div
      className={`room-detail-panel ${room ? "open" : ""}`}
      aria-hidden={!room}
    >
      <div className="panel-header">
        <div>
          <div className="eyebrow">Room</div>
          <h3>{room?.name || "Room"}</h3>
        </div>
        <button className="btn" onClick={onClose}>
          Close
        </button>
      </div>

      {!room && <div className="subhead">Select a room to view details.</div>}

      {room && (
        <div className="panel-content">
          <div className="subhead">Recent issues</div>
          <ul className="detail-list">
            {(room.issues || ["No recent issues."]).map((issue, idx) => (
              <li key={idx}>{issue}</li>
            ))}
          </ul>

          <div className="subhead">Sentiment (placeholder)</div>
          <div className="sentiment-chart">Sentiment chart placeholder</div>

          <div className="subhead">Threads</div>
          <ul className="detail-list">
            {(room.threads || ["No threads."]).map((t, idx) => (
              <li key={idx}>{t}</li>
            ))}
          </ul>

          <div className="subhead">Dependencies</div>
          <ul className="detail-list">
            {(room.dependencies || ["None"]).map((d, idx) => (
              <li key={idx}>{d}</li>
            ))}
          </ul>

          <div className="subhead">Upstream rooms</div>
          <ul className="detail-list">
            {(upstream.length ? upstream : ["None"]).map((u, idx) => (
              <li key={idx}>{u}</li>
            ))}
          </ul>

          <div className="subhead">Downstream rooms</div>
          <ul className="detail-list">
            {(downstream.length ? downstream : ["None"]).map((d, idx) => (
              <li key={idx}>{d}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
