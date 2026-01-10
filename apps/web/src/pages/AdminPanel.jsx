import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom"; // ✅ ADD THIS IMPORT
import "./Auth.css";
import { createOrganization, listOrganizations } from "../lib/tasksApi";
import { API_BASE_URL } from "../config";

export default function AdminPanel() {
  const navigate = useNavigate(); // ✅ ADD THIS HOOK
  const [me, setMe] = useState(null);
  const [loadingMe, setLoadingMe] = useState(true);
  const [orgs, setOrgs] = useState([]);
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const [createName, setCreateName] = useState("");
  const [copiedOrgId, setCopiedOrgId] = useState(null);

  const isAdmin = !!me?.is_platform_admin;

  useEffect(() => {
    const loadMe = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/me`, {
          credentials: "include",
        });
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

  useEffect(() => {
    const loadOrgs = async () => {
      if (!isAdmin) return;
      try {
        const data = await listOrganizations();
        setOrgs(data || []);
      } catch (err) {
        console.error("Failed to load orgs", err);
        setStatus("Could not load organizations.");
      }
    };
    loadOrgs();
  }, [isAdmin]);

  const handleCreate = async () => {
    if (!createName.trim()) {
      setStatus("Enter an organization name.");
      return;
    }
    setCreating(true);
    setStatus("");
    try {
      const created = await createOrganization(createName.trim());
      setOrgs((prev) => [created, ...prev]);
      setCreateName("");
      setStatus("Organization created.");
    } catch (err) {
      console.error("Create org failed", err);
      setStatus(err?.message || "Could not create organization.");
    } finally {
      setCreating(false);
    }
  };

  const copyCode = async (orgId, code) => {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopiedOrgId(orgId);
      setTimeout(() => setCopiedOrgId(null), 1500);
    } catch (err) {
      console.error("Copy failed", err);
      setStatus("Copy failed. Please copy manually.");
    }
  };

  if (loadingMe) {
    return (
      <div className="auth-container">
        <div className="auth-card glass">Loading admin panel…</div>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="auth-container">
        <div className="auth-card glass">
          <h3>Access denied</h3>
          <p className="subhead">This area is for platform admins only.</p>
          <button
            className="auth-button"
            onClick={() => navigate("/app")}
          >
            Go to app
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <div className="auth-card glass" style={{ width: "100%", maxWidth: 920, position: "relative" }}>
        {/* ✅ BACK BUTTON ADDED HERE */}
        <button
          className="auth-button"
          onClick={() => navigate("/app")}
          style={{
            position: "absolute",
            top: "20px",
            left: "20px",
            width: "auto",
            padding: "8px 16px",
            fontSize: "14px",
            background: "var(--color-surface)",
            border: "1px solid var(--border)",
          }}
        >
          ← Back to App
        </button>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "40px" }}>
          <div>
            <h2 className="auth-title">Admin</h2>
            <p className="auth-subtitle">
              Manage organizations and invite codes.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="auth-input"
              placeholder="Organization name"
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              style={{ minWidth: 220 }}
            />
            <button
              className="auth-button"
              onClick={handleCreate}
              disabled={creating}
            >
              {creating ? "Creating…" : "Create Organization"}
            </button>
          </div>
        </div>

        {status && <div className="auth-status" style={{ marginTop: 8 }}>{status}</div>}

        <div style={{ marginTop: 16 }}>
          <div className="eyebrow">Organizations</div>
          {orgs.length === 0 && <div className="subhead">No organizations yet.</div>}
          <div style={{ marginTop: 8, overflowX: "auto" }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Owner Email</th>
                  <th>Invite Code</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {orgs.map((org) => {
                  const code = org.invite_code || org.code || "";
                  const created =
                    org.created_at &&
                    new Date(org.created_at).toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                      hour: "numeric",
                      minute: "2-digit",
                    });
                  return (
                    <tr key={org.org_id || org.id}>
                      <td>{org.name || "—"}</td>
                      <td>{org.owner_email || "—"}</td>
                      <td className="mono">{code || "—"}</td>
                      <td>{created || "—"}</td>
                      <td>
                        <button
                          className="auth-button"
                          style={{ padding: "6px 10px" }}
                          onClick={() => copyCode(org.org_id || org.id, code)}
                        >
                          {copiedOrgId === (org.org_id || org.id) ? "Copied!" : "Copy code"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}