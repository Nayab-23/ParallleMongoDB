/**
 * ErrorBanner Component
 * Displays API errors with request_id and error_code for debugging
 */

import { useEffect, useState } from 'react';

export function ErrorBanner() {
  const [errors, setErrors] = useState([]);

  useEffect(() => {
    const handleApiError = (event) => {
      const { status, errorCode, message, requestId, timestamp } = event.detail;

      const newError = {
        id: Date.now() + Math.random(),
        status,
        errorCode,
        message,
        requestId,
        timestamp,
      };

      setErrors((prev) => [...prev, newError]);

      // Auto-dismiss after 10 seconds
      setTimeout(() => {
        setErrors((prev) => prev.filter((e) => e.id !== newError.id));
      }, 10000);
    };

    window.addEventListener('api-error', handleApiError);
    return () => window.removeEventListener('api-error', handleApiError);
  }, []);

  const dismissError = (id) => {
    setErrors((prev) => prev.filter((e) => e.id !== id));
  };

  if (errors.length === 0) {
    return null;
  }

  return (
    <div
      style={{
        position: 'fixed',
        top: '20px',
        right: '20px',
        zIndex: 10000,
        maxWidth: '500px',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
      }}
    >
      {errors.map((error) => (
        <div
          key={error.id}
          style={{
            background: '#fee',
            border: '2px solid #f66',
            borderRadius: '8px',
            padding: '16px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            fontFamily: 'monospace',
            fontSize: '13px',
            color: '#333',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              marginBottom: '8px',
            }}
          >
            <div style={{ fontWeight: 'bold', color: '#c00', fontSize: '14px' }}>
              {error.status ? `HTTP ${error.status}` : 'Network Error'}
            </div>
            <button
              onClick={() => dismissError(error.id)}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#999',
                cursor: 'pointer',
                fontSize: '18px',
                lineHeight: '1',
                padding: '0',
              }}
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>

          <div style={{ marginBottom: '8px', color: '#555' }}>
            {error.message}
          </div>

          {error.errorCode && (
            <div style={{ marginBottom: '4px' }}>
              <strong>Error Code:</strong> <code>{error.errorCode}</code>
            </div>
          )}

          {error.requestId && (
            <div style={{ marginBottom: '4px' }}>
              <strong>Request ID:</strong> <code>{error.requestId}</code>
            </div>
          )}

          <div style={{ fontSize: '11px', color: '#888', marginTop: '8px' }}>
            {new Date(error.timestamp).toLocaleTimeString()}
          </div>
        </div>
      ))}
    </div>
  );
}
