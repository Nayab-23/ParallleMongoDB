import React from "react";

const AIProcessingPanel = ({ data, timeline }) => {
  if (!data) {
    return (
      <div className="dashboard-stub">
        <h2>AI Processing</h2>
        <p>Waiting for data...</p>
      </div>
    );
  }

  return (
    <div className="dashboard-stub">
      <h2>AI Processing</h2>
      <div className="ai-stats">
        <div>
          <strong>Items Sent:</strong> {data.items_sent ?? 0}
        </div>
        <div>
          <strong>Items Returned:</strong> {data.items_returned ?? 0}
        </div>
        <div>
          <strong>Excluded:</strong> {data.items_excluded ?? 0}
        </div>
      </div>
      {data.categorization && (
        <div className="ai-categories">
          <strong>AI Categorization:</strong>
          <ul>
            {Object.entries(data.categorization).map(([category, items]) => (
              <li key={category}>
                {category}: {Array.isArray(items) ? items.length : items}
              </li>
            ))}
          </ul>
        </div>
      )}
      {timeline?.validation_fixes && (
        <div className="ai-validation">
          <strong>Validation Fixes:</strong>
          <ul>
            {timeline.validation_fixes.map((fix, idx) => (
              <li key={idx}>{fix}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default AIProcessingPanel;
