import { formatDistanceToNow } from "date-fns";

function formatLastActive(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return formatDistanceToNow(date, { addSuffix: true });
}

function normalizeText(value, fallback = "—") {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number") return String(value);
  return fallback;
}

export default function VscodeSessionsTable({
  sessions = [],
  loading = false,
  error = "",
  onRevoke = () => {},
}) {
  const rows = Array.isArray(sessions) ? sessions : [];

  return (
    <div className="vscode-table-section">
      {loading && <div className="vscode-muted">Loading sessions…</div>}
      {error && <div className="vscode-inline-error">{error}</div>}

      {!loading && !error && rows.length === 0 && (
        <div className="vscode-empty">No active sessions yet.</div>
      )}

      {!loading && !error && rows.length > 0 && (
        <div className="vscode-table-wrapper">
          <table className="vscode-table">
            <thead>
              <tr>
                <th>Device</th>
                <th>Workspace</th>
                <th>Last active</th>
                <th>Extension</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((session, idx) => {
                const id = session.id || session.session_id || session.uuid;
                const device =
                  session.device ||
                  session.device_name ||
                  session.machine ||
                  session.label;
                const workspace =
                  session.workspace?.name ||
                  session.workspace_name ||
                  session.workspace ||
                  session.workspace_id;
                const version =
                  session.extension_version ||
                  session.version ||
                  session.client_version;

                const key = id || device || idx;

                return (
                  <tr key={key}>
                    <td>{normalizeText(device)}</td>
                    <td>{normalizeText(workspace)}</td>
                    <td>{formatLastActive(session.last_active || session.last_seen_at || session.updated_at)}</td>
                    <td>{normalizeText(version)}</td>
                    <td style={{ textAlign: "right" }}>
                      {id ? (
                        <button
                          className="btn subtle"
                          onClick={() => onRevoke(id)}
                        >
                          Revoke
                        </button>
                      ) : (
                        <span className="vscode-muted">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
