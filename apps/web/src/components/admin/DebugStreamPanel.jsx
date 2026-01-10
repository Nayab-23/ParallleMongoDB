import React from "react";
import { useDebugStream } from "./DebugStreamContext";

const DebugStreamPanel = () => {
  const { events, clear } = useDebugStream();

  return (
    <div className="info-box" style={{ marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ fontWeight: 700 }}>Debug Stream (last {events.length}/50)</div>
        <button className="refresh-btn" onClick={clear} disabled={!events.length}>
          Clear
        </button>
      </div>
      <div style={{ maxHeight: 240, overflow: "auto", fontSize: 12 }}>
        {events.length === 0 && <div className="text-gray-500">No diagnostics yet</div>}
        {events
          .slice()
          .reverse()
          .map((evt, idx) => (
            <div key={idx} className="stage-item-row" style={{ alignItems: "flex-start" }}>
              <div className="stage-item-main">
                <div className="stage-item-title">
                  {evt.endpoint} • {evt.status}
                </div>
                <div className="stage-item-meta">
                  <span>req_id: {evt.envelope_request_id || evt.header_request_id || evt.client_request_id}</span>
                  {evt.backend_revision && <span>rev: {evt.backend_revision}</span>}
                  {evt.duration_ms !== undefined && <span>{evt.duration_ms} ms</span>}
                  {evt.handler && <span>handler: {evt.handler}</span>}
                </div>
                {evt.error_code && <div className="stage-item-reason">error_code: {evt.error_code}</div>}
                <div className="stage-item-meta">
                  <span>route: {evt.route || "n/a"}</span>
                  {evt.snapshot_key && <span>snapshot: {evt.snapshot_key}</span>}
                  {evt.snapshot_age && <span>age: {evt.snapshot_age}</span>}
                </div>
              </div>
              <button
                className="refresh-btn"
                onClick={() => navigator.clipboard?.writeText(JSON.stringify(evt, null, 2))}
              >
                Copy JSON
              </button>
            </div>
          ))}
      </div>
    </div>
  );
};

export default DebugStreamPanel;
