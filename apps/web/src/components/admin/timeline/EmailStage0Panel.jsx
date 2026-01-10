import React from "react";

/**
 * Email Stage 0 Panel
 *
 * Displays email filtering diagnostics that happen before Stage 0.
 * Shows counts, drop reasons, and sample dropped emails.
 *
 * Expected backend fields (all optional):
 * - email_stage_0.emails_fetched (number)
 * - email_stage_0.emails_valid (number)
 * - email_stage_0.emails_dropped (number)
 * - email_stage_0.drop_reasons (array of {reason: string, count: number})
 * - email_stage_0.sample_dropped_emails (array of {subject: string, reason: string})
 */

const EmailStage0Panel = ({ data }) => {
  // Gracefully handle missing data
  if (!data) {
    return (
      <div className="panel email-stage0-panel">
        <h3>📧 Email Stage 0 (Pre-Processing)</h3>
        <div className="panel-empty" style={{ padding: "16px", color: "#6b7280", fontStyle: "italic" }}>
          Email Stage 0 data not available. Backend needs to include <code>email_stage_0</code> field.
        </div>
      </div>
    );
  }

  const {
    emails_fetched = null,
    emails_valid = null,
    emails_dropped = null,
    drop_reasons = [],
    sample_dropped_emails = [],
  } = data;

  const hasData = emails_fetched !== null || emails_valid !== null || emails_dropped !== null;

  if (!hasData) {
    return (
      <div className="panel email-stage0-panel">
        <h3>📧 Email Stage 0 (Pre-Processing)</h3>
        <div className="panel-empty" style={{ padding: "16px", color: "#6b7280", fontStyle: "italic" }}>
          Email Stage 0 counts not available.
        </div>
      </div>
    );
  }

  return (
    <div className="panel email-stage0-panel" style={{ marginBottom: "16px" }}>
      <h3>📧 Email Stage 0 (Pre-Processing)</h3>

      {/* Counts Summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "12px", marginBottom: "16px" }}>
        <div className="stat-box" style={{
          padding: "12px",
          background: "#f3f4f6",
          borderRadius: "6px",
          textAlign: "center",
        }}>
          <div style={{ fontSize: "24px", fontWeight: 600, color: "#1f2937" }}>
            {emails_fetched !== null ? emails_fetched : "?"}
          </div>
          <div style={{ fontSize: "12px", color: "#6b7280", marginTop: "4px" }}>
            Emails Fetched
          </div>
        </div>

        <div className="stat-box" style={{
          padding: "12px",
          background: "#d1fae5",
          borderRadius: "6px",
          textAlign: "center",
        }}>
          <div style={{ fontSize: "24px", fontWeight: 600, color: "#065f46" }}>
            {emails_valid !== null ? emails_valid : "?"}
          </div>
          <div style={{ fontSize: "12px", color: "#047857", marginTop: "4px" }}>
            Valid Emails
          </div>
        </div>

        <div className="stat-box" style={{
          padding: "12px",
          background: "#fee2e2",
          borderRadius: "6px",
          textAlign: "center",
        }}>
          <div style={{ fontSize: "24px", fontWeight: 600, color: "#991b1b" }}>
            {emails_dropped !== null ? emails_dropped : "?"}
          </div>
          <div style={{ fontSize: "12px", color: "#dc2626", marginTop: "4px" }}>
            Dropped Emails
          </div>
        </div>
      </div>

      {/* Drop Reasons */}
      {drop_reasons && drop_reasons.length > 0 && (
        <div style={{ marginBottom: "16px" }}>
          <h4 style={{ fontSize: "14px", fontWeight: 600, marginBottom: "8px", color: "#374151" }}>
            Top Drop Reasons
          </h4>
          <div style={{
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: "6px",
            padding: "8px",
          }}>
            {drop_reasons.map((item, idx) => (
              <div
                key={idx}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "6px 8px",
                  borderBottom: idx < drop_reasons.length - 1 ? "1px solid #e5e7eb" : "none",
                }}
              >
                <span style={{ fontSize: "13px", color: "#374151" }}>{item.reason || "Unknown"}</span>
                <span style={{
                  fontSize: "13px",
                  fontWeight: 600,
                  color: "#dc2626",
                  background: "#fee2e2",
                  padding: "2px 8px",
                  borderRadius: "4px",
                }}>
                  {item.count || 0}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sample Dropped Emails */}
      {sample_dropped_emails && sample_dropped_emails.length > 0 && (
        <div>
          <h4 style={{ fontSize: "14px", fontWeight: 600, marginBottom: "8px", color: "#374151" }}>
            Sample Dropped Emails (up to 10)
          </h4>
          <div style={{
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: "6px",
            maxHeight: "300px",
            overflowY: "auto",
          }}>
            {sample_dropped_emails.slice(0, 10).map((email, idx) => (
              <div
                key={idx}
                style={{
                  padding: "10px 12px",
                  borderBottom: idx < Math.min(sample_dropped_emails.length, 10) - 1 ? "1px solid #e5e7eb" : "none",
                }}
              >
                <div style={{
                  fontSize: "13px",
                  fontWeight: 500,
                  color: "#1f2937",
                  marginBottom: "4px",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}>
                  {email.subject || "(No subject)"}
                </div>
                <div style={{
                  fontSize: "12px",
                  color: "#dc2626",
                  background: "#fef2f2",
                  display: "inline-block",
                  padding: "2px 6px",
                  borderRadius: "3px",
                }}>
                  {email.reason || "Unknown reason"}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* No drops detected */}
      {drop_reasons.length === 0 && sample_dropped_emails.length === 0 && emails_dropped === 0 && (
        <div style={{
          padding: "12px",
          background: "#d1fae5",
          border: "1px solid #10b981",
          borderRadius: "6px",
          color: "#065f46",
          fontSize: "13px",
          textAlign: "center",
        }}>
          ✅ All fetched emails were valid - no drops detected
        </div>
      )}
    </div>
  );
};

export default EmailStage0Panel;
