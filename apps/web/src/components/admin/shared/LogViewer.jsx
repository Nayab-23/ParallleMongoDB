import React, { useEffect, useRef } from "react";

const LogViewer = ({ logs = [], maxHeight = "400px", autoScroll = true }) => {
  const logRef = useRef(null);

  useEffect(() => {
    if (autoScroll && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  return (
    <div className="log-viewer">
      <div className="log-header">
        <span>Logs ({logs.length} lines)</span>
        <button onClick={() => downloadLogs(logs)} className="download-btn">
          📥 Download
        </button>
      </div>
      <div ref={logRef} className="log-content" style={{ maxHeight }}>
        {logs.map((log, index) => (
          <div key={index} className="log-line">
            <span className="log-timestamp">{log.timestamp}</span>
            <span className={`log-message ${getLogLevel(log.message)}`}>{log.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

function getLogLevel(message = "") {
  if (message.includes("ERROR") || message.includes("🔴")) return "error";
  if (message.includes("WARNING") || message.includes("⚠️")) return "warning";
  if (message.includes("SUCCESS") || message.includes("✅")) return "success";
  return "info";
}

function downloadLogs(logs = []) {
  const content = logs.map((log) => `${log.timestamp || ""} ${log.message || ""}`).join("\n");
  const blob = new Blob([content], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `timeline-logs-${Date.now()}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

export default LogViewer;
