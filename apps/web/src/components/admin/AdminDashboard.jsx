import React, { useEffect, useState } from "react";
import { Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import TimelineDebugDashboard from "./timeline/TimelineDebugDashboard";
import VSCodeDebugDashboard from "./vscode/VSCodeDebugDashboard";
import CollaborationDebugDashboard from "./collaboration/CollaborationDebugDashboard";
import SystemOverviewDashboard from "./system/SystemOverviewDashboard";
import OrganizationManagement from "./org/OrganizationManagement";
import AdminLogsDashboard from "./logsTab/AdminLogsDashboard";
import WaitlistDashboard from "./waitlist/WaitlistDashboard";
import { API_BASE_URL } from "../../config";
import { adminPing, getAdminLogs, adminSelftest } from "../../api/adminApi";
import "./AdminDashboard.css";
import AdminErrorBoundary from "./AdminErrorBoundary";
import { DebugStreamProvider } from "./DebugStreamContext";
import DebugStreamPanel from "./DebugStreamPanel";

const AdminDashboard = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const [me, setMe] = useState(null);
  const [loadingMe, setLoadingMe] = useState(true);
  const [status, setStatus] = useState("");
  const [logsAvailable, setLogsAvailable] = useState(true);

  // Connectivity test state
  const [pingStatus, setPingStatus] = useState(null);
  const [pinging, setPinging] = useState(false);
  const [consoleDebug, setConsoleDebug] = useState(() => {
    if (typeof localStorage === "undefined") return false;
    return localStorage.getItem("ADMIN_DEBUG") === "1";
  });
  const [selftestResult, setSelftestResult] = useState(null);
  const [selftestOpen, setSelftestOpen] = useState(false);
  const [selftesting, setSelftesting] = useState(false);

  const tabs = [
    { id: "timeline", label: "Timeline Debug", path: "/admin/timeline-debug" },
    { id: "vscode", label: "VSCode Debug", path: "/admin/vscode-debug" },
    { id: "collaboration", label: "Collaboration", path: "/admin/collaboration-debug" },
    { id: "system", label: "System Overview", path: "/admin/system-overview" },
    { id: "waitlist", label: "Waitlist", path: "/admin/waitlist" },
    { id: "logs", label: "Logs", path: "/admin/logs" },
    { id: "organizations", label: "Organizations", path: "/admin/organizations" },
  ];

  const activeTab = tabs.find((tab) => location.pathname.startsWith(tab.path))?.id || "timeline";

  useEffect(() => {
    const loadMe = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/me`, { credentials: "include" });
        if (!res.ok) throw new Error("Not authenticated");
        const data = await res.json();
        setMe(data);
      } catch (err) {
        console.error("Failed to load user", err);
        setStatus("Not authenticated.");
      } finally {
        setLoadingMe(false);
      }
    };
    loadMe();
  }, []);

  // Check if logs endpoint exists (non-blocking)
  useEffect(() => {
    const checkLogs = async () => {
      try {
        await getAdminLogs("timeline", 1);
        setLogsAvailable(true);
      } catch (err) {
        if (err?.status === 404) {
          setLogsAvailable(false);
        }
      }
    };
    checkLogs();
  }, []);

  useEffect(() => {
    try {
      if (consoleDebug) {
        localStorage.setItem("ADMIN_DEBUG", "1");
      } else {
        localStorage.setItem("ADMIN_DEBUG", "0");
      }
    } catch {
      // ignore storage errors
    }
  }, [consoleDebug]);

  const isAdmin = me?.is_platform_admin === true;

  // Test admin connectivity
  const testAdminConnection = async () => {
    setPinging(true);
    setPingStatus(null);

    try {
      const result = await adminPing();
      if (result?.success) {
        setPingStatus({
          success: true,
          message: result.message || "✅ Connected as platform admin",
          details: result,
        });
      } else {
        const err = result?.error || {};
        const msg = err.message || "Connection failed";
        const status = err.status || result?.status;
        let message = "❌ ";
        if (status === 401) {
          message += "Not authenticated";
        } else if (status === 403) {
          message += "Not a platform admin";
        } else if (status === 404) {
          message += "Admin ping endpoint not implemented (404)";
        } else if (status === 0) {
          message += "Cannot connect to backend";
        } else {
          message += msg;
        }
        setPingStatus({
          success: false,
          message,
          details: result,
        });
      }
    } catch (error) {
      setPingStatus({
        success: false,
        message: error?.message || "Connection failed",
        details: error,
      });
    } finally {
      setPinging(false);
    }
  };

  if (loadingMe) {
    return (
      <div className="admin-dashboard">
        <div className="admin-card">Loading admin dashboard...</div>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="admin-dashboard">
        <div className="admin-card">
          <h3>Access denied</h3>
          <p className="admin-subhead">{status || "This area is for platform admins only."}</p>
          <button className="admin-primary-btn" onClick={() => navigate("/app")}>
            Go to app
          </button>
        </div>
      </div>
    );
  }

  return (
    <DebugStreamProvider>
      <div className="admin-dashboard">
      <div className="admin-header">
        <div>
          <h1>Admin Debug Dashboard</h1>
          <p className="admin-subhead">Monitor and debug core system features</p>
        </div>
        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "13px" }}>
            <input
              type="checkbox"
              checked={consoleDebug}
              onChange={(e) => setConsoleDebug(e.target.checked)}
            />
            Console debug
          </label>
          <button
            onClick={async () => {
              setSelftesting(true);
              try {
                const res = await adminSelftest();
                setSelftestResult(res);
                setSelftestOpen(true);
                if (localStorage.getItem("ADMIN_DEBUG") === "1") {
                  console.log("[ADMIN_SELFTEST]", res);
                }
              } catch (err) {
                setSelftestResult({
                  success: false,
                  error: { message: err?.message || "Selftest failed", status: err?.status },
                  request_id: err?.request_id,
                  duration_ms: err?.duration_ms,
                });
                setSelftestOpen(true);
              } finally {
                setSelftesting(false);
              }
            }}
            disabled={selftesting}
            className="refresh-btn"
            style={{ fontSize: "13px", padding: "8px 14px" }}
          >
            {selftesting ? "Running..." : "Run Selftest"}
          </button>
          <button
            onClick={testAdminConnection}
            disabled={pinging}
            className="refresh-btn"
            style={{ fontSize: "13px", padding: "8px 14px" }}
          >
            {pinging ? "Testing..." : "Test Admin Connection"}
          </button>
        </div>
      </div>

      {pingStatus && (
        <div
          className={pingStatus.success ? "ping-success" : "ping-error"}
          style={{
            padding: "12px 16px",
            marginBottom: "16px",
            borderRadius: "6px",
            border: `1px solid ${pingStatus.success ? "#10b981" : "#ef4444"}`,
            backgroundColor: pingStatus.success ? "#d1fae5" : "#fee2e2",
            color: pingStatus.success ? "#065f46" : "#991b1b",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "4px" }}>{pingStatus.message}</div>
          {!pingStatus.success && pingStatus.details && (
            <details style={{ fontSize: "12px", marginTop: "8px", cursor: "pointer" }}>
              <summary>Debug Details (status: {pingStatus.details.status || "unknown"})</summary>
              <pre
                style={{
                  marginTop: "8px",
                  padding: "8px",
                  background: "rgba(0,0,0,0.05)",
                  borderRadius: "4px",
                  overflow: "auto",
                  maxHeight: "200px",
                }}
              >
                {JSON.stringify(pingStatus.details, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}

      <div className="admin-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`admin-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => navigate(tab.path)}
          >
            {tab.label}
            {tab.id === "logs" && !logsAvailable && (
              <span className="tab-badge muted">Not available</span>
            )}
          </button>
        ))}
      </div>

      <DebugStreamPanel />

      <div className="admin-content">
        <AdminErrorBoundary>
          <Routes>
            <Route path="/" element={<Navigate to="/admin/timeline-debug" replace />} />
            <Route path="/timeline-debug" element={<TimelineDebugDashboard />} />
            <Route path="/vscode-debug" element={<VSCodeDebugDashboard />} />
            <Route path="/collaboration-debug" element={<CollaborationDebugDashboard />} />
            <Route path="/system-overview" element={<SystemOverviewDashboard />} />
            <Route path="/waitlist" element={<WaitlistDashboard />} />
            <Route path="/logs" element={<AdminLogsDashboard />} />
            <Route path="/organizations" element={<OrganizationManagement />} />
          </Routes>
        </AdminErrorBoundary>
      </div>

      {selftestOpen && (
        <div className="admin-modal-backdrop">
          <div className="admin-modal">
            <div className="modal-header">
              <h3>Admin Selftest</h3>
              <button onClick={() => setSelftestOpen(false)} className="close-btn">
                ✕
              </button>
            </div>
            <div className="modal-body">
              {selftestResult ? (
                <>
                  <div style={{ fontWeight: 600, marginBottom: 8 }}>
                    {selftestResult.success ? "✅ Passed" : "❌ Failed"}
                  </div>
                  {selftestResult.request_id && (
                    <div className="error-meta">request_id: {selftestResult.request_id}</div>
                  )}
                  {selftestResult.duration_ms !== undefined && (
                    <div className="error-meta">duration: {selftestResult.duration_ms}ms</div>
                  )}
                  {selftestResult.error?.message && (
                    <div style={{ marginTop: 8 }}>
                      <strong>Error:</strong> {String(selftestResult.error.message)}
                    </div>
                  )}
                  <details style={{ marginTop: 12 }}>
                    <summary>Raw response</summary>
                    <pre className="error-body">
                      {JSON.stringify(selftestResult, null, 2)}
                    </pre>
                  </details>
                </>
              ) : (
                <div>Loading selftest result...</div>
              )}
            </div>
          </div>
        </div>
      )}
      </div>
    </DebugStreamProvider>
  );
};

export default AdminDashboard;
