import { useEffect, useMemo, useState } from "react";
import "./Auth.css";
import "./SettingsPage.css";
import { API_BASE_URL } from "../config";
import { listOAuthApps, revokeOAuthApp } from "../api/oauthApps";
import { startConnect } from "../api/integrations/vscode";
import {
  getIntegrationsStatus,
  disconnectIntegration,
  setCanonRefreshInterval,
} from "../lib/tasksApi";
import FilteredEventsPanel from "../components/FilteredEventsPanel";

const CANON_REFRESH_OPTIONS = [
  { value: 0, label: "Disabled" },
  { value: 1, label: "1m" },
  { value: 15, label: "15m" },
  { value: 30, label: "30m" },
  { value: 60, label: "60m" },
  { value: 120, label: "2h" },
  { value: 360, label: "6h" },
  { value: 720, label: "12h" },
  { value: 1440, label: "24h" },
];
const CANON_REFRESH_VALUES = new Set(
  CANON_REFRESH_OPTIONS.map((option) => option.value)
);

const providers = [
  {
    id: "gmail",
    title: "Gmail",
    description: "Connect Gmail to surface important emails in your Daily Brief.",
    connectPath: `${API_BASE_URL}/api/integrations/google/gmail/start`,
    disconnectKey: "gmail",
  },
  {
    id: "calendar",
    title: "Google Calendar",
    description: "Sync Calendar so upcoming meetings are summarized for you.",
    connectPath: `${API_BASE_URL}/api/integrations/google/calendar/start`,
    disconnectKey: "calendar",
  },
];

function normalizeOAuthApps(payload) {
  const list =
    Array.isArray(payload)
      ? payload
      : payload?.apps ||
        payload?.items ||
        payload?.sessions ||
        payload?.data ||
        [];
  return list.map((entry) => ({
    id: entry.id || entry.app_id || entry.session_id || entry.token_id || entry.client_id,
    name:
      entry.name ||
      entry.app_name ||
      entry.client_name ||
      entry.application ||
      entry.client_id ||
      "Connected app",
    clientId:
      entry.client_id ||
      entry.app_id ||
      entry.client ||
      entry.id ||
      entry.session_id,
    lastUsed:
      entry.last_used_at ||
      entry.last_active ||
      entry.updated_at ||
      entry.last_seen_at ||
      entry.created_at,
    scopes: entry.scopes || entry.scope || entry.permissions,
  }));
}

function isVscodeConnection(app) {
  const haystack = [app.name, app.clientId, app.id]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes("vscode") || haystack.includes("parallel-vscode");
}

function formatAppTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatAppScopes(scopes) {
  if (!scopes) return "";
  if (Array.isArray(scopes)) return scopes.join(", ");
  if (typeof scopes === "string") return scopes;
  return "";
}

export default function SettingsPage() {
  const [me, setMe] = useState(null);
  const [loadingMe, setLoadingMe] = useState(true);
  const [status, setStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState({});
  const [toast, setToast] = useState("");
  const [canonInterval, setCanonInterval] = useState(1);
  const [savingCanon, setSavingCanon] = useState(false);
  const [canonToast, setCanonToast] = useState("");
  const [canonError, setCanonError] = useState("");
  const [canonOAuthWarning, setCanonOAuthWarning] = useState(null);
  const [resetting, setResetting] = useState(false);
  const [oauthApps, setOauthApps] = useState([]);
  const [oauthAppsLoading, setOauthAppsLoading] = useState(false);
  const [oauthAppsError, setOauthAppsError] = useState("");
  const [oauthAppsNotice, setOauthAppsNotice] = useState("");
  const [oauthAppsBusy, setOauthAppsBusy] = useState({});
  const [connectingVscode, setConnectingVscode] = useState(false);

  // Load current user to gate access
  useEffect(() => {
    const loadMe = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/me`, {
          credentials: "include",
        });
        if (!res.ok) throw new Error("Not authenticated");
        const data = await res.json();
        console.log("[Settings] /api/me response", data);
        setMe(data);

        const intervalPref = data?.preferences?.canon_refresh_interval_minutes;
        console.log("[Settings] interval pref", intervalPref);
        const parsed = Number(intervalPref);
        const normalized = CANON_REFRESH_VALUES.has(parsed) ? parsed : 1;
        setCanonInterval(normalized);
      } catch (err) {
        console.error("Failed to load user", err);
        // DEV MODE: Don't redirect to login
        // window.location.href = "/login";
      } finally {
        setLoadingMe(false);
      }
    };
    loadMe();
  }, []);

  useEffect(() => {
    const stored = localStorage.getItem("canonOAuthError");
    if (!stored) return;
    try {
      const parsed = JSON.parse(stored);
      if (parsed?.error === "oauth_refresh_failed") {
        setCanonOAuthWarning(parsed);
      }
    } catch (err) {
      console.warn("[Settings] Failed to parse canonOAuthError", err);
    }
  }, []);

  // Handle URL params (connected=xxx)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("connected");
    if (connected) {
      setToast(`${connected} connected successfully.`);
      params.delete("connected");
      const newUrl =
        window.location.pathname +
        (params.toString() ? `?${params.toString()}` : "");
      window.history.replaceState({}, "", newUrl);
    }
  }, []);

  const loadStatus = async () => {
    setLoadingStatus(true);
    setError("");
    try {
      const data = await getIntegrationsStatus();
      setStatus(data);
    } catch (err) {
      console.error("Integration status failed", err);
      setError("Could not load integration status.");
    } finally {
      setLoadingStatus(false);
    }
  };

  const loadOAuthApps = async () => {
    setOauthAppsLoading(true);
    setOauthAppsError("");
    try {
      const data = await listOAuthApps();
      setOauthApps(normalizeOAuthApps(data));
    } catch (err) {
      console.error("Failed to load connected apps", err);
      setOauthAppsError("Could not load connected apps.");
    } finally {
      setOauthAppsLoading(false);
    }
  };

  useEffect(() => {
    if (me) loadStatus();
  }, [me]);

  useEffect(() => {
    if (me) loadOAuthApps();
  }, [me]);

  const providerState = useMemo(() => {
    const base = status || {};
    return {
      gmail: base.gmail || base.google_gmail || {},
      calendar: base.calendar || base.google_calendar || {},
    };
  }, [status]);

  const vscodeApps = useMemo(
    () => oauthApps.filter((app) => isVscodeConnection(app)),
    [oauthApps]
  );

  const intervalStatus = useMemo(() => {
    if (savingCanon) return "Saving auto-refresh...";
    if (canonInterval === 0) return "Auto-refresh disabled";
    if (canonInterval < 60) {
      return `Auto-refresh every ${canonInterval} minute${canonInterval === 1 ? "" : "s"}`;
    }
    const hours = canonInterval / 60;
    return `Auto-refresh every ${hours} hour${hours === 1 ? "" : "s"}`;
  }, [canonInterval, savingCanon]);

  const getReconnectPath = (provider) => {
    const normalized =
      provider === "google_gmail" || provider === "gmail"
        ? "gmail"
        : provider === "google_calendar" || provider === "calendar"
        ? "calendar"
        : null;
    const match = providers.find((p) => p.id === normalized);
    return match?.connectPath || null;
  };

  const handleReconnect = () => {
    const path = getReconnectPath(canonOAuthWarning?.provider);
    if (path) {
      window.location.href = path;
      return;
    }
    window.location.href = "/settings";
  };

  const dismissOAuthWarning = () => {
    localStorage.removeItem("canonOAuthError");
    setCanonOAuthWarning(null);
  };

  const handleConnect = (path) => {
    window.location.href = path;
  };

  const handleDisconnect = async (providerId) => {
    setBusy((prev) => ({ ...prev, [providerId]: true }));
    setToast("");
    try {
      await disconnectIntegration(providerId);
      setToast(`${providerId} disconnected.`);
      await loadStatus();
    } catch (err) {
      console.error("Disconnect failed", err);
      setToast("We couldn’t disconnect right now. Try again.");
    } finally {
      setBusy((prev) => {
        const next = { ...prev };
        delete next[providerId];
        return next;
      });
    }
  };

  const handleConnectVscode = async () => {
    setOauthAppsNotice("");
    setOauthAppsError("");
    setConnectingVscode(true);
    try {
      const data = await startConnect();
      const url =
        data?.authorization_url || data?.auth_url || data?.url || data?.redirect_url;
      if (url) {
        window.open(url, "_blank", "noopener,noreferrer");
        setOauthAppsNotice("Browser opened for VS Code authorization.");
      } else {
        setOauthAppsError("No authorization URL returned.");
      }
    } catch (err) {
      console.error("Failed to start VS Code connect", err);
      setOauthAppsError("Could not start VS Code connect flow.");
    } finally {
      setConnectingVscode(false);
    }
  };

  const handleRevokeApp = async (appId) => {
    if (!appId) return;
    setOauthAppsBusy((prev) => ({ ...prev, [appId]: true }));
    setOauthAppsNotice("");
    setOauthAppsError("");
    try {
      await revokeOAuthApp(appId);
      setOauthAppsNotice("VS Code access revoked.");
      await loadOAuthApps();
    } catch (err) {
      console.error("Failed to revoke app", err);
      setOauthAppsError("Could not revoke app access.");
    } finally {
      setOauthAppsBusy((prev) => {
        const next = { ...prev };
        delete next[appId];
        return next;
      });
    }
  };

  const saveCanonRefresh = async (nextInterval, previousInterval) => {
    setSavingCanon(true);
    setCanonToast("");
    setCanonError("");
    console.log("[Settings] Saving canon interval", nextInterval);
    try {
      await setCanonRefreshInterval(Number(nextInterval));

      console.log("[Settings] Save success, updating local state");
      setCanonToast("Auto-refresh settings saved");
      setMe((prev) =>
        prev
          ? {
              ...prev,
              preferences: {
                ...(prev.preferences || {}),
                canon_refresh_interval_minutes: Number(nextInterval),
              },
            }
          : prev
      );
    } catch (err) {
      console.error("Failed to save canon refresh setting", err);
      setCanonError(err?.message || "Couldn't save settings. Try again.");
      if (typeof previousInterval === "number") {
        setCanonInterval(previousInterval);
      }
    } finally {
      setSavingCanon(false);
    }
  };

  const handleIntervalChange = (value) => {
    if (savingCanon || value === canonInterval) return;
    const previous = canonInterval;
    setCanonInterval(value);
    saveCanonRefresh(value, previous);
  };

  const handleResetTimeline = async () => {
    if (!window.confirm(
      'This will DELETE all timeline data and deletion history.\n\n' +
      'Your calendar events will regenerate fresh in ~1 minute.\n\n' +
      'Continue?'
    )) {
      return;
    }

    try {
      setResetting(true);
      setToast('');
      setError('');

      const response = await fetch(`${API_BASE_URL}/api/debug/reset-timeline`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errorData.detail || `HTTP ${response.status}`);
      }

      const data = await response.json();

      alert(
        `✅ Timeline Reset Complete!\n\n` +
        `Deleted: ${data.deleted_items || 0} items\n\n` +
        `Timeline will regenerate in ~1 minute.`
      );

      // Reload the page to refresh timeline
      window.location.reload();
    } catch (err) {
      console.error('[Reset Error]', err);
      setError(`Reset failed: ${err.message}`);
    } finally {
      setResetting(false);
    }
  };

  if (loadingMe) {
    return (
      <div className="auth-container">
        <div className="auth-card glass">Loading settings…</div>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <div className="auth-card glass" style={{ width: "100%", maxWidth: 800, textAlign: "left" }}>
        <h2 className="auth-title">Settings</h2>
        <p className="auth-subtitle">Connect your tools to power the Daily Brief.</p>

        {toast && <div className="auth-status">{toast}</div>}
        {canonToast && (
          <div className="settings-toast success" role="status">
            <span className="settings-toast-icon">✅</span>
            <span>{canonToast}</span>
          </div>
        )}
        {error && (
          <div className="auth-status" style={{ marginBottom: 8 }}>
            {error}{" "}
            <button
              className="auth-button"
              style={{ width: "auto", padding: "6px 10px", display: "inline-flex", marginLeft: 8 }}
              onClick={loadStatus}
            >
              Retry
            </button>
          </div>
        )}

        {loadingStatus && <div className="subhead">Loading integrations…</div>}

        <div className="settings-card">
          <div className="settings-card-header">
            <div>
              <div className="settings-card-title">Canon Auto-Refresh</div>
              <p className="settings-card-description">
                How often Parallel should check for new emails and calendar events to update your timeline
              </p>
            </div>
          </div>
          <div className="settings-control">
            <label htmlFor="canonInterval" className="settings-label">
              Refresh interval
            </label>
            <select
              id="canonInterval"
              className="settings-select"
              value={canonInterval}
              onChange={(e) => handleIntervalChange(Number(e.target.value))}
              disabled={savingCanon}
            >
              {CANON_REFRESH_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <div className="settings-helper">{intervalStatus}</div>
          </div>
          {canonOAuthWarning && (
            <div className="settings-toast error settings-warning" role="status">
              <span className="settings-toast-icon">⚠️</span>
              <div className="settings-warning-text">
                <div className="settings-warning-title">Connection required</div>
                <div className="settings-warning-message">
                  {canonOAuthWarning.message || "Please reconnect your account."}
                </div>
              </div>
              <div className="settings-warning-actions">
                <button
                  type="button"
                  className="settings-warning-btn primary"
                  onClick={handleReconnect}
                >
                  Reconnect
                </button>
                <button
                  type="button"
                  className="settings-warning-btn secondary"
                  onClick={dismissOAuthWarning}
                >
                  Dismiss
                </button>
              </div>
            </div>
          )}
          {canonError && (
            <div className="settings-toast error" role="status">
              <span className="settings-toast-icon">⚠️</span>
              <span>{canonError}</span>
            </div>
          )}
        </div>

        <div className="settings-grid">
          {providers.map((p) => {
            const info = providerState[p.id] || {};
            const connected = !!info.connected;
            const healthy = info.healthy !== false;
            const needsReconnect = info.needs_reconnect === true;
            const updated =
              info.updated_at &&
              new Date(info.updated_at).toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
              });

            // Determine status badge
            let statusBadge = { text: "Not connected", bg: "rgba(255,255,255,0.04)", color: "var(--text-secondary)", icon: "❌" };
            if (connected && needsReconnect) {
              statusBadge = { text: "Expired", bg: "#FFF4E6", color: "#FF9500", icon: "⚠️" };
            } else if (connected && healthy) {
              statusBadge = { text: "Connected", bg: "rgba(0,200,0,0.1)", color: "#0a8", icon: "✅" };
            } else if (connected && !healthy) {
              statusBadge = { text: "Unhealthy", bg: "#FEF2F2", color: "#DC2626", icon: "⚠️" };
            }

            return (
              <div key={p.id} className="settings-card">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{p.title}</div>
                    <div className="subhead" style={{ marginTop: 4 }}>
                      {p.description}
                    </div>
                  </div>
                  <span
                    className="integration-status-badge"
                    style={{
                      padding: "6px 10px",
                      borderRadius: "999px",
                      border: "1px solid var(--border)",
                      background: statusBadge.bg,
                      color: statusBadge.color,
                      fontSize: 12,
                      fontWeight: 600,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "4px",
                    }}
                  >
                    <span>{statusBadge.icon}</span>
                    <span>{statusBadge.text}</span>
                  </span>
                </div>

                {updated && (
                  <div className="roles" style={{ marginTop: 6 }}>
                    Last updated: {updated}
                  </div>
                )}

                <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                  {connected ? (
                    <>
                      {needsReconnect && (
                        <button
                          className="auth-button"
                          style={{
                            width: "auto",
                            padding: "10px 14px",
                            background: "linear-gradient(135deg, #FF9500, #FFB340)",
                          }}
                          onClick={() => handleConnect(p.connectPath)}
                        >
                          Reconnect
                        </button>
                      )}
                      <button
                        className="auth-button"
                        style={{
                          width: "auto",
                          padding: "10px 14px",
                          background: needsReconnect ? "rgba(0,0,0,0.05)" : undefined,
                          color: needsReconnect ? "#6E6E73" : undefined,
                        }}
                        disabled={busy[p.id]}
                        onClick={() => handleDisconnect(p.disconnectKey)}
                      >
                        {busy[p.id] ? "Disconnecting…" : "Disconnect"}
                      </button>
                    </>
                  ) : (
                    <button
                      className="auth-button"
                      style={{ width: "auto", padding: "10px 14px" }}
                      onClick={() => handleConnect(p.connectPath)}
                    >
                      Connect
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="settings-card" style={{ marginTop: 20 }}>
          <div className="settings-card-header">
            <div>
              <div className="settings-card-title">Connected Apps</div>
              <p className="settings-card-description">
                Manage apps that can access your Parallel workspace.
              </p>
            </div>
            <button
              className="auth-button"
              style={{ width: "auto", padding: "10px 14px" }}
              onClick={handleConnectVscode}
              disabled={connectingVscode}
            >
              {connectingVscode ? "Opening..." : "Connect VS Code"}
            </button>
          </div>

          {oauthAppsNotice && (
            <div className="settings-toast success" role="status">
              <span className="settings-toast-icon">✅</span>
              <span>{oauthAppsNotice}</span>
            </div>
          )}
          {oauthAppsError && (
            <div className="settings-toast error" role="status">
              <span className="settings-toast-icon">⚠️</span>
              <span>{oauthAppsError}</span>
            </div>
          )}

          {oauthAppsLoading && <div className="subhead">Loading connected apps…</div>}
          {!oauthAppsLoading && vscodeApps.length === 0 && (
            <div className="subhead">No VS Code connections yet.</div>
          )}

          {!oauthAppsLoading && vscodeApps.length > 0 && (
            <div className="settings-app-list">
              {vscodeApps.map((app, idx) => {
                const appId = app.id || app.clientId || `${app.name}-${idx}`;
                const lastUsed = formatAppTimestamp(app.lastUsed);
                const scopes = formatAppScopes(app.scopes);
                const metaParts = [];
                if (app.clientId) metaParts.push(`Client ID: ${app.clientId}`);
                if (lastUsed) metaParts.push(`Last used: ${lastUsed}`);
                if (scopes) metaParts.push(`Scopes: ${scopes}`);
                const metaText = metaParts.join(" • ");

                return (
                  <div key={appId} className="settings-app-row">
                    <div>
                      <div className="settings-app-name">{app.name || "VS Code"}</div>
                      {metaText && <div className="settings-app-meta">{metaText}</div>}
                    </div>
                    <div className="settings-app-actions">
                      <button
                        className="auth-button"
                        style={{ width: "auto", padding: "10px 14px" }}
                        onClick={() => handleRevokeApp(appId)}
                        disabled={oauthAppsBusy[appId]}
                      >
                        {oauthAppsBusy[appId] ? "Revoking…" : "Revoke"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Filtered Events Management */}
        <div style={{ marginTop: 32 }}>
          <FilteredEventsPanel />
        </div>

        {/* Debug Tools */}
        <div className="debug-section">
          <h3>⚠️ Debug Tools</h3>
          <p className="subhead">Reset timeline and deletion history for testing</p>
          <button
            onClick={handleResetTimeline}
            disabled={resetting}
            className="btn-danger"
          >
            {resetting ? 'Resetting...' : '🔄 Reset Timeline & History'}
          </button>
        </div>
      </div>
    </div>
  );
}
