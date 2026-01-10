// src/pages/InviteGate.jsx
import { useState } from "react";
import "./Auth.css";
import { API_BASE_URL } from "../config";

export default function InviteGate({ user, onDone }) {
  const [inviteCode, setInviteCode] = useState("");
  const [role, setRole] = useState(user?.role || "");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  const roleOptions =
    (import.meta.env.VITE_ROLE_OPTIONS ||
      "Product,Engineering,Design,Data,Ops,Other")
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setStatus("");
    setLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/activate`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          invite_code: inviteCode || null,
          role: role || null,
        }),
      });

      if (!res.ok) {
        let detail = "Activation failed.";
        try {
          const data = await res.json();
          if (data?.detail) detail = data.detail;
        } catch {
          // ignore parse error, keep default message
        }
        setStatus(detail);
        setLoading(false);
        return;
      }

      // success → let AppLayout re-check /me
      if (onDone) {
        onDone();
      } else {
        // fallback if onDone isn’t provided
        window.location.href = '/app';
      }
    } catch (err) {
      console.error("InviteGate activate error", err);
      setStatus("Something went wrong. Please try again.");
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-card glass">
        <h2 className="auth-title">Finish setting up your workspace</h2>
        <p className="auth-subtitle">
          Hi {user?.name || user?.email}, Parallel is currently invite-only.
          Use your team&apos;s invite code and role to activate your account.
        </p>

        <form onSubmit={handleSubmit}>
          <input
            className="auth-input"
            type="text"
            placeholder="Invite code"
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
          />

          <select
            className="auth-input"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="">Role (optional - defaults to Member)</option>
            {roleOptions.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>

          {status && <div className="auth-status">{status}</div>}

          <button
            className="auth-button"
            type="submit"
            disabled={loading}
          >
            {loading ? "Activating…" : "Activate workspace"}
          </button>
        </form>

        <p className="auth-footer" style={{ marginTop: "1rem" }}>
          Don&apos;t have a code? Email{" "}
          <a href="mailto:founder@parallelos.ai">founder@parallelos.ai</a>.
        </p>
      </div>
    </div>
  );
}
