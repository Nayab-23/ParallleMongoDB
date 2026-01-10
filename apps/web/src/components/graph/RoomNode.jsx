import { memo, useState } from "react";
import { Handle, Position } from "@xyflow/react";
import RoomHoverCard from "./RoomHoverCard";

const statusColor = (status) => {
  if (!status) return "#888";
  if (status === "healthy") return "#0a8";
  if (status === "strained") return "#d9a500";
  if (status === "critical") return "#d92f2f";
  return "#666";
};

function RoomNode({ data }) {
  const [hover, setHover] = useState(false);

  return (
    <div
      className="room-node"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={() => data?.onOpen?.(data)}
    >
      <div className="room-node-header">
        <div className="room-node-name">{data.name}</div>
        <span
          className="room-node-status"
          style={{
            borderColor: statusColor(data.status),
            color: statusColor(data.status),
          }}
        >
          {data.status || "unknown"}
        </span>
      </div>
      <div className="room-node-metrics">
        <span>Fires: {data.fires ?? 0}</span>
        <span>Sentiment: {data.sentiment ?? "—"}</span>
        <span>Overdue: {data.overdue ?? 0}</span>
      </div>
      <Handle type="target" position={Position.Top} />
      <Handle type="source" position={Position.Bottom} />
      {hover && <RoomHoverCard data={data} />}
    </div>
  );
}

export default memo(RoomNode);
