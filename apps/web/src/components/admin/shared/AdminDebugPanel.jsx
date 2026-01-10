import React from 'react';
import './AdminDebugPanel.css';

/**
 * AdminDebugPanel - Reusable component for displaying API request debug info
 *
 * Shows:
 * - Request ID and duration
 * - HTTP status
 * - Timestamp
 * - Collapsible error details
 * - Collapsible full debug JSON
 *
 * Usage:
 *   <AdminDebugPanel response={apiResponse} />
 *
 * Where apiResponse is the normalized response from adminFetch:
 *   { success, data, error, debug, request_id, duration_ms, status }
 */
const AdminDebugPanel = ({ response, className = '' }) => {
  if (!response) {
    return null;
  }

  const { success, error, debug, request_id, duration_ms, status, data } = response;
  const url = debug?.url;
  const errorMessage =
    typeof error === "object"
      ? error?.message || JSON.stringify(error, null, 2)
      : error;

  // Determine status color
  let statusColor = '#10b981'; // green for success
  if (status >= 500) statusColor = '#ef4444'; // red for server error
  else if (status >= 400) statusColor = '#f59e0b'; // orange for client error
  else if (status === 0) statusColor = '#6b7280'; // gray for network error

  return (
    <div className={`admin-debug-panel ${className}`}>
      {/* Summary bar */}
      <div className="debug-summary">
        <div className="debug-meta">
          <span className="debug-label">Request ID:</span>
          <code className="debug-value">{request_id || 'N/A'}</code>
        </div>
        {url && (
          <div className="debug-meta">
            <span className="debug-label">URL:</span>
            <code className="debug-value">{url}</code>
          </div>
        )}
        <div className="debug-meta">
          <span className="debug-label">Duration:</span>
          <code className="debug-value">{duration_ms !== undefined ? `${duration_ms}ms` : 'N/A'}</code>
        </div>
        <div className="debug-meta">
          <span className="debug-label">Status:</span>
          <code className="debug-value" style={{ color: statusColor, fontWeight: 600 }}>
            {status !== undefined ? status : 'N/A'}
          </code>
        </div>
        {debug?.timestamp && (
          <div className="debug-meta">
            <span className="debug-label">Time:</span>
            <code className="debug-value">
              {new Date(debug.timestamp).toLocaleTimeString()}
            </code>
          </div>
        )}
        {debug && (
          <div className="debug-meta">
            <span className="debug-label">Shape:</span>
            <code className="debug-value">
              {debug.legacy ? "Legacy-wrapped" : "Envelope"}
            </code>
          </div>
        )}
      </div>

      {/* Error section (if present) */}
      {!success && error && (
        <div className="debug-error-section">
          <div className="debug-error-message">
            ❌ {errorMessage}
          </div>
        </div>
      )}

      {/* Collapsible debug details */}
      {debug && (
        <details className="debug-details">
          <summary className="debug-summary-toggle">
            🔍 Full Debug Information
          </summary>
          <pre className="debug-json">
            {JSON.stringify(debug, null, 2)}
          </pre>
        </details>
      )}

      {/* Raw response payload */}
      <details className="debug-details">
        <summary className="debug-summary-toggle">
          🧾 Raw Response
        </summary>
        <pre className="debug-json">
          {JSON.stringify({ data, error, debug }, null, 2)}
        </pre>
      </details>
    </div>
  );
};

export default AdminDebugPanel;
