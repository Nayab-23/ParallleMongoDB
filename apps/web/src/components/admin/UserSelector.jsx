import React, { useEffect, useState } from "react";
import { getAdminUsers, formatAdminError } from "../../api/adminApi";

const UserSelector = ({ value, onChange, placeholder = "Select user..." }) => {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const didFetchRef = React.useRef(false);

  useEffect(() => {
    if (didFetchRef.current) return;
    didFetchRef.current = true;
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await getAdminUsers();
      const users =
        resp?.data?.users ??
        resp?.users ??
        [];

      if (!Array.isArray(users)) {
        setError({
          message: "Users response is not an array",
          status: resp?.status,
          request_id: resp?.request_id,
          body: resp,
        });
        setUsers([]);
        return;
      }

      setUsers(users);
    } catch (err) {
      console.error("Failed to fetch users:", err);
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  if (error) {
    const bodyText = error?.body ? JSON.stringify(error.body, null, 2) : null;
    return (
      <div className="user-selector-error">
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Failed to load users</div>
        <div className="error-meta">
          {error.status ? `Status: ${error.status}` : "Status: unknown"}{" "}
          {error.status === 500 ? "(Backend error - check Admin Logs tab)" : ""}
        </div>
        {error.request_id && (
          <div className="error-meta">request_id: {error.request_id}</div>
        )}
        <div style={{ marginTop: 4, fontSize: 12 }}>
          Message: {error.message || "Unknown error"}
        </div>
        <div style={{ marginTop: 4, fontSize: 12 }}>{formatAdminError(error)}</div>
        {error.request_id && (
          <div className="error-meta">request_id: {error.request_id}</div>
        )}
        {bodyText && (
          <pre className="error-body" style={{ marginTop: 8 }}>
            {bodyText}
          </pre>
        )}
        <button onClick={fetchUsers} className="retry-btn">
          Retry
        </button>
      </div>
    );
  }

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="user-selector"
      disabled={loading}
    >
      <option value="">{loading ? "Loading users..." : placeholder}</option>
      {users.map((user) => (
        <option key={user.email || user.id} value={user.email}>
          {user.name || user.email}
        </option>
      ))}
    </select>
  );
};

export default UserSelector;
