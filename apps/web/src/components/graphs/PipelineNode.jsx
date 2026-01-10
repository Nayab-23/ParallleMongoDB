import React from "react";
import "./PipelineNode.css";

const statusClass = (status) => {
  switch ((status || "").toLowerCase()) {
    case "running":
    case "executing":
      return "status-executing";
    case "completed":
      return "status-completed";
    case "failed":
      return "status-failed";
    case "modified":
      return "status-modified";
    case "queued":
      return "status-pending";
    default:
      return "status-pending";
  }
};

const StatusDot = ({ status }) => {
  const cls = statusClass(status);
  return <span className={`status-dot ${cls}`} />;
};

export default function PipelineNode({ data, id, nodeRun }) {
  const currentStatus = nodeRun?.status || data.status;
  const cls = statusClass(currentStatus);
  return (
    <div className={`pipeline-node ${cls}`}>
      <div className="node-header">
        <StatusDot status={currentStatus} />
        <span className="node-title">{data.label || data.type || id}</span>
      </div>
      {data.executionTime && (
        <div className="node-meta">{data.executionTime} ms</div>
      )}
      {currentStatus && <div className="node-status-text">{currentStatus}</div>}
      {nodeRun?.lastError && (
        <div className="node-meta" style={{ color: "#dc2626", fontSize: 12 }}>
          Error
        </div>
      )}
      {nodeRun?.lastOutputPreview && (
        <div className="node-meta" style={{ fontSize: 11 }}>
          Output preview
        </div>
      )}
    </div>
  );
}
