import React, { useState, useEffect } from 'react';
import { getAdminUsers, formatAdminError } from '../../api/adminApi';

const MultiUserSelector = ({ selected, onChange, max = 4, placeholder = "Select users..." }) => {
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
      console.error('❌ [ADMIN/MultiUserSelector] Failed to fetch users:', err);
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = (userEmail) => {
    console.log('👥 [ADMIN/MultiUserSelector] Toggling user:', userEmail);
    if (selected.includes(userEmail)) {
      console.log('👥 [ADMIN/MultiUserSelector] Removing user from selection');
      onChange(selected.filter(u => u !== userEmail));
    } else {
      if (selected.length < max) {
        console.log('👥 [ADMIN/MultiUserSelector] Adding user to selection');
        onChange([...selected, userEmail]);
      } else {
        console.warn('⚠️ [ADMIN/MultiUserSelector] Max users reached:', max);
      }
    }
  };

  if (error) {
    const bodyText = error?.body ? JSON.stringify(error.body, null, 2) : null;
    return (
      <div className="multi-user-selector-error" style={{
        padding: '10px 14px',
        background: '#fee2e2',
        border: '1px solid #ef4444',
        borderRadius: '6px',
        color: '#991b1b',
        fontSize: '13px'
      }}>
        <div style={{ fontWeight: 600 }}>Failed to load users</div>
        <div style={{ fontSize: '12px', marginTop: '4px' }}>
          Status: {error?.status || 'unknown'} {error?.status === 500 ? '(Backend error - check Admin Logs tab)' : ''}
        </div>
        {error?.request_id && (
          <div style={{ fontSize: '12px', marginTop: '4px' }}>
            request_id: {error.request_id}
          </div>
        )}
        <div style={{ fontSize: '12px', marginTop: '4px' }}>
          Message: {error?.message || 'Unknown error'}
        </div>
        <div style={{ marginTop: '4px', fontSize: '12px' }}>
          {formatAdminError(error)}
        </div>
        {error?.status && (
          <div style={{ fontSize: '12px', marginTop: '4px' }}>
            Status: {error.status} {error.status === 500 ? '(Backend error - check Admin Logs tab)' : ''}
          </div>
        )}
        {bodyText && (
          <pre className="error-body" style={{ marginTop: 6 }}>
            {bodyText}
          </pre>
        )}
        <button onClick={fetchUsers} className="retry-btn" style={{ marginTop: 8 }}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="multi-user-selector">
      <div className="selected-users">
        {selected.map(userEmail => {
          const user = users.find(u => u.email === userEmail);
          return (
            <span key={userEmail} className="selected-user-badge">
              {user?.name || userEmail}
              <button onClick={() => handleToggle(userEmail)} className="remove-btn">✕</button>
            </span>
          );
        })}
        {selected.length === 0 && (
          <span className="placeholder-text">{placeholder}</span>
        )}
      </div>

      <div className="users-dropdown">
        {loading ? (
          <div className="loading-text">Loading users...</div>
        ) : (
          <select
            onChange={(e) => {
              if (e.target.value) {
                handleToggle(e.target.value);
                e.target.value = '';
              }
            }}
            value=""
            disabled={selected.length >= max}
            className="user-select"
          >
            <option value="">
              {selected.length >= max ? `Max ${max} users selected` : 'Add user...'}
            </option>
            {users
              .filter(u => !selected.includes(u.email))
              .map(user => (
                <option key={user.email} value={user.email}>
                  {user.name || user.email}
                </option>
              ))}
          </select>
        )}
      </div>
    </div>
  );
};

export default MultiUserSelector;
