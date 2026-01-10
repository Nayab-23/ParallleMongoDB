import { useEffect, useState } from "react";
import { getOrganizations, createOrganization, formatAdminError } from "../../../api/adminApi";
import './OrganizationManagement.css';

const OrganizationManagement = () => {
  const [orgs, setOrgs] = useState([]);
  const [creating, setCreating] = useState(false);
  const [createName, setCreateName] = useState("");
  const [copiedOrgId, setCopiedOrgId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState("");

  useEffect(() => {
    loadOrgs();
  }, []);

  const loadOrgs = async () => {
    console.log('🏢 [ADMIN/OrgManagement] Loading organizations...');
    setLoading(true);
    setError(null);
    try {
      const data = await getOrganizations();
      console.log('🏢 [ADMIN/OrgManagement] Organizations loaded:', data?.length || 0, 'orgs');
      console.log('🏢 [ADMIN/OrgManagement] Organization data:', data);
      setOrgs(data || []);
    } catch (err) {
      console.error('❌ [ADMIN/OrgManagement] Failed to load orgs:', err);
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!createName.trim()) {
      console.warn('⚠️ [ADMIN/OrgManagement] Empty organization name');
      setError({ message: "Enter an organization name" });
      return;
    }
    console.log('🏢 [ADMIN/OrgManagement] Creating organization:', createName.trim());
    setCreating(true);
    setError(null);
    setSuccessMessage("");
    try {
      const created = await createOrganization(createName.trim());
      console.log('✅ [ADMIN/OrgManagement] Organization created:', created);
      setOrgs((prev) => [created, ...prev]);
      setCreateName("");
      setSuccessMessage(`Organization "${created.name}" created successfully with invite code: ${created.invite_code}`);
      setTimeout(() => setSuccessMessage(""), 5000);
    } catch (err) {
      console.error('❌ [ADMIN/OrgManagement] Create org failed:', err);
      setError(err);
    } finally {
      setCreating(false);
    }
  };

  const copyCode = async (orgId, code) => {
    if (!code) {
      console.warn('⚠️ [ADMIN/OrgManagement] No code to copy for org:', orgId);
      return;
    }
    console.log('📋 [ADMIN/OrgManagement] Copying invite code for org:', orgId);
    try {
      await navigator.clipboard.writeText(code);
      console.log('✅ [ADMIN/OrgManagement] Invite code copied to clipboard');
      setCopiedOrgId(orgId);
      setTimeout(() => setCopiedOrgId(null), 1500);
    } catch (err) {
      console.error('❌ [ADMIN/OrgManagement] Copy failed:', err);
      setError({ message: "Copy failed. Please copy manually." });
    }
  };

  return (
    <div className="org-management">
      <div className="org-management-header">
        <div>
          <h2>Organization Management</h2>
          <p className="org-subtitle">Create and manage organizations and invite codes</p>
        </div>
        <div className="create-org-controls">
          <input
            className="org-input"
            placeholder="Organization name"
            value={createName}
            onChange={(e) => setCreateName(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleCreate()}
          />
          <button
            className="create-org-btn"
            onClick={handleCreate}
            disabled={creating}
          >
            {creating ? "Creating…" : "Create Organization"}
          </button>
        </div>
      </div>

      {/* Success Message */}
      {successMessage && (
        <div
          style={{
            padding: "12px 16px",
            marginBottom: "16px",
            background: "#d1fae5",
            border: "1px solid #10b981",
            borderRadius: "6px",
            color: "#065f46",
          }}
        >
          ✅ {successMessage}
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div
          style={{
            padding: "16px",
            marginBottom: "16px",
            background: "#fee2e2",
            border: "1px solid #ef4444",
            borderRadius: "8px",
            color: "#991b1b",
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "8px" }}>Failed to load organizations</div>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              fontSize: "12px",
              fontFamily: "monospace",
              margin: 0,
            }}
          >
            {formatAdminError(error)}
          </pre>
          {error.status && (
            <details style={{ marginTop: "12px", fontSize: "12px" }}>
              <summary style={{ cursor: "pointer", fontWeight: 500 }}>
                Error Details (HTTP {error.status})
              </summary>
              <pre
                style={{
                  marginTop: "8px",
                  padding: "12px",
                  background: "rgba(0,0,0,0.05)",
                  borderRadius: "4px",
                  overflow: "auto",
                }}
              >
                {JSON.stringify(error, null, 2)}
              </pre>
            </details>
          )}
          <button
            onClick={loadOrgs}
            style={{
              marginTop: "12px",
              padding: "8px 16px",
              background: "#dc2626",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "13px",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {loading ? (
        <div className="org-loading">Loading organizations...</div>
      ) : (
        <div className="org-table-container">
          {orgs.length === 0 ? (
            <div className="org-empty">No organizations yet. Create one to get started.</div>
          ) : (
            <table className="org-table">
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
                      <td className="org-name">{org.name || "—"}</td>
                      <td>{org.owner_email || "—"}</td>
                      <td className="org-code">
                        <code style={{
                          background: "#f3f4f6",
                          padding: "2px 6px",
                          borderRadius: "3px",
                          fontFamily: "monospace"
                        }}>
                          {code || "—"}
                        </code>
                      </td>
                      <td className="org-date">{created || "—"}</td>
                      <td>
                        <button
                          className="copy-code-btn"
                          onClick={() => copyCode(org.org_id || org.id, code)}
                          disabled={!code}
                        >
                          {copiedOrgId === (org.org_id || org.id) ? "✓ Copied!" : "Copy code"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div className="org-info">
        <h3>How Invite Codes Work</h3>
        <ul>
          <li>Each organization has a unique invite code</li>
          <li>Share the code with users to invite them to join the organization</li>
          <li>Users can join using: <code>POST /api/org/join</code> with <code>{`{"invite_code": "abc123xyz"}`}</code></li>
          <li>The first user to join gets full frontend and backend permissions</li>
          <li>Users can check their organization with: <code>GET /api/org/me</code></li>
        </ul>
      </div>
    </div>
  );
};

export default OrganizationManagement;
