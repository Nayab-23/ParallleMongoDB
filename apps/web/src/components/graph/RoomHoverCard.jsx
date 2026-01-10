import { createPortal } from "react-dom";

export default function RoomHoverCard({ data }) {
  const box = (
    <div className="room-hover-card">
      <div className="room-hover-title">{data.name}</div>
      <div className="room-hover-row">Status: {data.status || "unknown"}</div>
      <div className="room-hover-row">Fires: {data.fires ?? 0}</div>
      <div className="room-hover-row">Sentiment: {data.sentiment ?? "—"}</div>
      <div className="room-hover-row">Overdue: {data.overdue ?? 0}</div>
      <button
        className="btn"
        style={{ marginTop: 8 }}
        onClick={(e) => {
          e.stopPropagation();
          data?.onOpen?.(data);
        }}
      >
        Open Room Brief
      </button>
    </div>
  );
  return createPortal(box, document.body);
}
