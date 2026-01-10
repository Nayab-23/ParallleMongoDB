import React from "react";

const GuardrailsPanel = ({ data }) => {
  if (!data) {
    return (
      <div className="dashboard-stub">
        <h2>Guardrails</h2>
        <p>No guardrail data yet.</p>
      </div>
    );
  }

  return (
    <div className="dashboard-stub">
      <h2>Guardrails</h2>
      <div className="guardrails-grid">
        {data.before && (
          <div>
            <strong>Before:</strong>
            <pre className="guardrails-pre">{JSON.stringify(data.before, null, 2)}</pre>
          </div>
        )}
        {data.after && (
          <div>
            <strong>After:</strong>
            <pre className="guardrails-pre">{JSON.stringify(data.after, null, 2)}</pre>
          </div>
        )}
        {data.backfill_triggered !== undefined && (
          <div>
            <strong>Backfill Triggered:</strong> {data.backfill_triggered ? "Yes" : "No"}
          </div>
        )}
      </div>
    </div>
  );
};

export default GuardrailsPanel;
