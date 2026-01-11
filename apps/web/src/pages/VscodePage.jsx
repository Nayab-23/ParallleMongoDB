import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./VscodePage.css";
import {
  getStatus,
  startConnect,
  listSessions,
  revokeSession,
  disconnectAll,
  savePreferences,
} from "../api/integrations/vscode";
import VscodeGetStartedCard from "../components/vscode/VscodeGetStartedCard";
import VscodeSessionsTable from "../components/vscode/VscodeSessionsTable";

const MARKETPLACE_URL = "https://marketplace.visualstudio.com/items?itemName=parallel.parallel-vscode";
const DOCS_URL = "https://docs.parallel.so/vscode";
const CONNECT_TIMEOUT_MS = 30000;
const CONNECT_POLL_MS = 2000;
const LOCAL_PREF_KEY = "vscode_default_workspace";

function isConnectedStatus(data) {
  if (!data) return false;
  if (data.connected === true) return true;
  const status =
    data.status ||
    data.state ||
    data.connection_status ||
    data.integration_status;
  if (status && String(status).toLowerCase() === "connected") return true;
  if (data.authorized === true || data.is_connected === true) return true;
  if (Array.isArray(data.sessions) && data.sessions.length > 0) return true;
  return false;
}

function normalizeSessions(raw) {
  if (!raw) return [];
  const list = Array.isArray(raw?.sessions)
    ? raw.sessions
    : Array.isArray(raw?.items)
    ? raw.items
    : Array.isArray(raw)
    ? raw
    : [];
  return list.map((session) => ({
    ...session,
    id: session.id || session.session_id || session.uuid,
    device:
      session.device ||
      session.device_name ||
      session.machine ||
      session.label,
    workspace:
      session.workspace?.name ||
      session.workspace_name ||
      session.workspace ||
      session.workspace_id ||
      session.org_name,
    last_active: session.last_active || session.last_seen_at || session.updated_at,
    version:
      session.extension_version || session.version || session.client_version,
  }));
}

function resolveWorkspaceOptions(status, user) {
  if (Array.isArray(status?.available_workspaces)) return status.available_workspaces;
  if (Array.isArray(status?.workspaces)) return status.workspaces;
  if (Array.isArray(user?.workspaces)) return user.workspaces;
  if (Array.isArray(user?.orgs)) return user.orgs;
  return [];
}

export default function VscodePage({ user }) {
  const [status, setStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState("");
  const [authIssue, setAuthIssue] = useState("");
  const [comingSoon, setComingSoon] = useState(false);

  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState("");

  const [connectState, setConnectState] = useState("idle");
  const [connectError, setConnectError] = useState("");

  const [selectedWorkspace, setSelectedWorkspace] = useState("");
  const [savingWorkspace, setSavingWorkspace] = useState(false);
  const [prefMessage, setPrefMessage] = useState("");

  const pollTokenRef = useRef(0);
  const pollControllerRef = useRef(null);

  const workspaceOptions = useMemo(
    () => resolveWorkspaceOptions(status, user),
    [status, user]
  );

  useEffect(() => {
    const stored = localStorage.getItem(LOCAL_PREF_KEY);
    if (stored) {
      setSelectedWorkspace(stored);
    }
  }, []);

  useEffect(() => {
    const pref =
      status?.preferences?.default_workspace_id ||
      status?.default_workspace_id;
    if (pref && !selectedWorkspace) {
      setSelectedWorkspace(String(pref));
    }
  }, [status, selectedWorkspace]);

  useEffect(() => {
    if (!selectedWorkspace && workspaceOptions.length > 0) {
      const first = workspaceOptions[0];
      const value =
        first.id ||
        first.workspace_id ||
        first.value ||
        first.slug ||
        first;
      if (value) {
        setSelectedWorkspace(String(value));
      }
    }
  }, [selectedWorkspace, workspaceOptions]);

  const connected = useMemo(
    () => isConnectedStatus(status) || connectState === "connected",
    [status, connectState]
  );

  const cancelActivePoll = useCallback(() => {
    pollTokenRef.current += 1;
    if (pollControllerRef.current) {
      try {
        pollControllerRef.current.abort();
      } catch {
        // ignore abort errors
      }
      pollControllerRef.current = null;
    }
  }, []);

  const loadStatus = useCallback(
    async (opts = { silent: false }) => {
      const { silent } = opts || {};
      if (!silent) {
        setStatusLoading(true);
      }
      setStatusError("");
      setAuthIssue("");
      setComingSoon(false);
      try {
        const data = await getStatus();
        setStatus(data || {});
        return data;
      } catch (err) {
        const httpStatus = err?.status;
        if (httpStatus === 401) {
          setAuthIssue("Please sign in");
        } else if (httpStatus === 403) {
          setAuthIssue("Not authorized");
        } else if (httpStatus === 404) {
          setComingSoon(true);
        } else {
          setStatusError("Could not load VS Code status. Please try again.");
        }
        return null;
      } finally {
        if (!silent) {
          setStatusLoading(false);
        }
      }
    },
    []
  );

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    setSessionsError("");
    try {
      const data = await listSessions();
      setSessions(normalizeSessions(data));
    } catch (err) {
      const httpStatus = err?.status;
      if (httpStatus === 401) {
        setAuthIssue("Session expired");
      } else if (httpStatus === 403) {
        setAuthIssue("Not authorized");
      } else if (httpStatus === 404) {
        setComingSoon(true);
      } else {
        setSessionsError("Could not load sessions.");
      }
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadStatus().then((data) => {
      if (!cancelled && isConnectedStatus(data)) {
        loadSessions();
      }
    });
    return () => {
      cancelled = true;
    };
  }, [loadStatus, loadSessions]);

  useEffect(() => {
    if (connected) {
      loadSessions();
    }
  }, [connected, loadSessions]);

  useEffect(() => {
    return () => {
      cancelActivePoll();
    };
  }, [cancelActivePoll]);

  const pollForApproval = useCallback(async () => {
    cancelActivePoll();
    const controller = new AbortController();
    pollControllerRef.current = controller;
    const pollToken = pollTokenRef.current;
    const finalize = () => {
      if (pollControllerRef.current === controller) {
        pollControllerRef.current = null;
      }
    };

    setConnectState("polling");
    setConnectError("");
    const start = Date.now();

    while (Date.now() - start < CONNECT_TIMEOUT_MS) {
      if (pollTokenRef.current !== pollToken) {
        return;
      }
      try {
        const latest = await getStatus(controller.signal);
        if (pollTokenRef.current !== pollToken) {
          return;
        }
        const normalized = latest || {};
        setStatus(normalized);
        if (isConnectedStatus(normalized)) {
          setConnectState("connected");
          await loadSessions();
          finalize();
          return;
        }
      } catch (err) {
        if (pollTokenRef.current !== pollToken) {
          return;
        }
        if (err?.name === "AbortError") {
          return;
        }
        const httpStatus = err?.status;
        if (httpStatus === 401) {
          setAuthIssue("Session expired");
          setConnectState("idle");
          finalize();
          return;
        }
        if (httpStatus === 403) {
          setAuthIssue("Not authorized");
          setConnectState("idle");
          finalize();
          return;
        }
        if (httpStatus === 404) {
          setComingSoon(true);
          setConnectState("idle");
          finalize();
          return;
        }
        setConnectError(err?.message || "Could not verify status.");
        setConnectState("timeout");
        finalize();
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, CONNECT_POLL_MS));
    }

    if (pollTokenRef.current !== pollToken) {
      return;
    }
    setConnectState("timeout");
    finalize();
  }, [cancelActivePoll, loadSessions]);

  const handleBrowserConnect = async () => {
    cancelActivePoll();
    setConnectError("");
    setConnectState("starting");
    try {
      const data = await startConnect();
      const url =
        data?.authorization_url || data?.auth_url || data?.url || data?.redirect_url;
      if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
      }
      await pollForApproval();
    } catch (err) {
      setConnectError(err?.message || "Could not start connect flow.");
      setConnectState("idle");
    }
  };

  const handleApproved = () => {
    pollForApproval();
  };

  const handleRetry = () => {
    cancelActivePoll();
    setConnectError("");
    setConnectState("idle");
  };

  const handleRevokeSession = async (id) => {
    try {
      await revokeSession(id);
      await loadSessions();
      await loadStatus({ silent: true });
    } catch (err) {
      setSessionsError(err?.message || "Could not revoke session.");
    }
  };

  const handleDisconnectAll = async () => {
    setSessionsError("");
    setStatusError("");
    try {
      await disconnectAll();
      await loadSessions();
      await loadStatus({ silent: true });
      setConnectState("idle");
    } catch (err) {
      setStatusError(err?.message || "Could not disconnect right now.");
    }
  };

  const handleSaveWorkspace = async () => {
    if (!selectedWorkspace) return;
    setSavingWorkspace(true);
    setPrefMessage("");
    try {
      await savePreferences({ default_workspace_id: selectedWorkspace });
      setPrefMessage("Saved as default workspace.");
      localStorage.setItem(LOCAL_PREF_KEY, selectedWorkspace);
    } catch (err) {
      localStorage.setItem(LOCAL_PREF_KEY, selectedWorkspace);
      if (err?.status === 404) {
        setPrefMessage("Saved locally until the backend is ready.");
      } else {
        setPrefMessage("Saved locally. Sync when available.");
      }
    } finally {
      setSavingWorkspace(false);
    }
  };

  const handleInstall = () => window.open(MARKETPLACE_URL, "_blank", "noopener,noreferrer");
  const handleDocs = () => window.open(DOCS_URL, "_blank", "noopener,noreferrer");

  const statusLabel = connected ? "Connected" : "Not connected";

  // DEV MODE: Don't block on auth issues
  // if (authIssue) {
  //   return (
  //     <div className="vscode-page">
  //       <div className="vscode-card glass">
  //         <div className="vscode-card-header">
  //           <h3>{authIssue}</h3>
  //         </div>
  //         <p className="vscode-muted">
  //           Please{" "}
  //           <a href="/login" className="vscode-link">
  //             sign in
  //           </a>{" "}
  //           to set up the VS Code extension.
  //         </p>
  //       </div>
  //     </div>
  //   );
  // }

  return (
    <div className="vscode-page">
      <div className="vscode-header">
        <div className="vscode-title">
          <div className="eyebrow">PARALLEL IDE</div>
          <h1>VS Code Extension</h1>
          <p className="vscode-subtitle">
            Run Parallel Agent inside your editor with workspace context.
          </p>
        </div>
        <div className={`vscode-pill ${connected ? "success" : "neutral"}`}>
          {statusLabel}
        </div>
      </div>

      {statusLoading && (
        <div className="vscode-card glass">
          <div className="vscode-muted">Checking VS Code status…</div>
        </div>
      )}

      {!statusLoading && statusError && (
        <div className="vscode-card glass">
          <div className="vscode-inline-error">{statusError}</div>
        </div>
      )}

      {!statusLoading && (
        <div className="vscode-grid">
          {!connected ? (
            <>
              <VscodeGetStartedCard
                onInstall={handleInstall}
                onViewDocs={handleDocs}
                onConnect={handleBrowserConnect}
                connectState={connectState}
                connectError={connectError}
                onApproved={handleApproved}
                onRetry={handleRetry}
                workspaceOptions={workspaceOptions}
                selectedWorkspace={selectedWorkspace}
                onWorkspaceChange={setSelectedWorkspace}
                onSaveWorkspace={handleSaveWorkspace}
                savingWorkspace={savingWorkspace}
                showWorkspacePicker={workspaceOptions.length > 1}
                comingSoon={comingSoon}
                preferenceMessage={prefMessage}
              />
              <div className="vscode-card glass vscode-permissions">
                <div className="eyebrow">Permissions</div>
                <h3>What VS Code can access</h3>
                <ul>
                  <li>
                    <span className="vscode-perm-icon">📋</span>
                    <span>View your tasks and todo items</span>
                  </li>
                  <li>
                    <span className="vscode-perm-icon">💬</span>
                    <span>Access assistant chat history</span>
                  </li>
                  <li>
                    <span className="vscode-perm-icon">🏢</span>
                    <span>View workspace metadata and settings</span>
                  </li>
                </ul>
                <div className="vscode-security-note">
                  <strong>🔒 Security:</strong> Applying code changes always requires your explicit confirmation in VS Code. 
                  The extension cannot modify files without your approval.
                </div>
              </div>
              <div className="vscode-card glass vscode-how-it-works">
                <div className="eyebrow">How it works</div>
                <h3>OAuth Authorization Flow</h3>
                <ol className="vscode-flow-steps">
                  <li>
                    <span className="vscode-flow-num">1</span>
                    <span>Open VS Code and run <code>Parallel: Sign In</code> from Command Palette</span>
                  </li>
                  <li>
                    <span className="vscode-flow-num">2</span>
                    <span>Your browser opens to authorize the connection</span>
                  </li>
                  <li>
                    <span className="vscode-flow-num">3</span>
                    <span>Click "Authorize" on the approval page</span>
                  </li>
                  <li>
                    <span className="vscode-flow-num">4</span>
                    <span>VS Code automatically receives the connection</span>
                  </li>
                </ol>
              </div>
            </>
          ) : (
            <>
              <div className="vscode-card glass">
                <div className="vscode-card-header">
                  <div>
                    <div className="eyebrow">Sessions</div>
                    <h3>Manage</h3>
                    <p className="vscode-muted">
                      Review connected editors, revoke sessions, or disconnect completely.
                    </p>
                  </div>
                  <div className="vscode-actions">
                    <button className="btn ghost" onClick={handleDocs}>
                      Open setup instructions
                    </button>
                    <button className="btn" onClick={handleDisconnectAll}>
                      Disconnect all
                    </button>
                  </div>
                </div>
                {workspaceOptions.length > 1 && (
                  <div className="vscode-workspace-row" style={{ marginBottom: 8 }}>
                    <div className="vscode-muted" style={{ minWidth: 180 }}>
                      Default workspace for VS Code
                    </div>
                    <select
                      className="vscode-select"
                      value={selectedWorkspace}
                      onChange={(e) => setSelectedWorkspace(e.target.value)}
                    >
                      {workspaceOptions.map((ws) => {
                        const value =
                          ws.id ||
                          ws.workspace_id ||
                          ws.value ||
                          ws.slug ||
                          ws;
                        const optionValue = value != null ? String(value) : "";
                        const label =
                          ws.name || ws.title || ws.label || ws.org_name || optionValue;
                        return (
                          <option key={optionValue} value={optionValue}>
                            {label}
                          </option>
                        );
                      })}
                    </select>
                    <button
                      className="btn primary"
                      onClick={handleSaveWorkspace}
                      disabled={savingWorkspace}
                    >
                      {savingWorkspace ? "Saving…" : "Save"}
                    </button>
                  </div>
                )}
                {prefMessage && <div className="vscode-success-banner">{prefMessage}</div>}
                <VscodeSessionsTable
                  sessions={sessions}
                  loading={sessionsLoading}
                  error={sessionsError}
                  onRevoke={handleRevokeSession}
                />
              </div>

              <div className="vscode-card glass vscode-permissions">
                <div className="eyebrow">Permissions</div>
                <h3>Access</h3>
                <ul>
                  <li>VS Code can read: tasks, assistant chat history, workspace metadata.</li>
                  <li>Applying code changes requires explicit confirmation in VS Code.</li>
                </ul>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
