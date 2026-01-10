import { useEffect, useState } from "react";
import "./Auth.css";
import { joinOrganization } from "../lib/tasksApi";

export default function JoinWorkspace({ user, onJoined }) {
  const [inviteCode, setInviteCode] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasOrg, setHasOrg] = useState(!!user?.org_id);

  useEffect(() => {
    if (user && user.org_id) {
      setHasOrg(true);
    }
  }, [user]);

  const handleJoin = async () => {
    if (!inviteCode.trim()) {
      setStatus("Enter your workspace invite code.");
      return;
    }
    setLoading(true);
    setStatus("");
    try {
      await joinOrganization(inviteCode.trim());
      setStatus("Joined! Redirecting…");
      if (onJoined) {
        onJoined();
      } else {
        window.location.href = "/app";
      }
    } catch (err) {
      const msg =
        err?.message || "Could not join workspace. Check the invite code.";
      setStatus(msg);
    } finally {
      setLoading(false);
    }
  };

  const onKey = (e) => {
    if (e.key === "Enter") handleJoin();
  };

  if (hasOrg) {
    return (
      <div className="auth-container">
        <motion.div
          className="auth-card glass"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <h2 className="auth-title">You’re already in a workspace</h2>
          <p className="auth-subtitle">
            Head to your dashboard to keep working.
          </p>
          <button
            className="auth-button"
            onClick={() => (window.location.href = "/app")}
          >
            Go to Dashboard
          </button>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="auth-container">
      <motion.div
        className="auth-card glass"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <h2 className="auth-title">Join Workspace</h2>
        <p className="auth-subtitle">
          Enter the invite code provided by your workspace admin.
        </p>

        <input
          className="auth-input"
          placeholder="Workspace invite code"
          value={inviteCode}
          onChange={(e) => setInviteCode(e.target.value)}
          onKeyDown={onKey}
        />

        {status && <div className="auth-status">{status}</div>}

        <button className="auth-button" onClick={handleJoin} disabled={loading}>
          {loading ? "Joining..." : "Join Workspace"}
        </button>

        <div className="auth-footer" style={{ marginTop: 12 }}>
          If you don’t have a code, contact your workspace admin.
        </div>
      </motion.div>
    </div>
  );
}
