import React from 'react';
import './AdminErrorBoundary.css';

/**
 * AdminErrorBoundary - React Error Boundary for admin tabs
 *
 * Catches JavaScript errors anywhere in the child component tree,
 * logs those errors, and displays a fallback UI instead of crashing the whole app.
 *
 * Usage:
 *   <AdminErrorBoundary tabName="Timeline Debug">
 *     <TimelineDebugTab />
 *   </AdminErrorBoundary>
 */
class AdminErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      errorCount: 0,
    };
  }

  static getDerivedStateFromError(error) {
    // Update state so the next render will show the fallback UI
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    // Log error details
    console.error(`[AdminErrorBoundary] ❌ Error in ${this.props.tabName || 'Admin Tab'}:`, error);
    console.error('[AdminErrorBoundary] Error Info:', errorInfo);

    this.setState(prevState => ({
      error,
      errorInfo,
      errorCount: prevState.errorCount + 1,
    }));
  }

  handleReset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render() {
    if (this.state.hasError) {
      const { tabName = 'This Tab' } = this.props;
      const { error, errorInfo, errorCount } = this.state;

      return (
        <div className="admin-error-boundary">
          <div className="error-boundary-header">
            <div className="error-icon">⚠️</div>
            <div>
              <h3 className="error-title">{tabName} Crashed</h3>
              <p className="error-subtitle">
                Something went wrong in this admin tab. The rest of the admin panel is still working.
              </p>
            </div>
          </div>

          {error && (
            <div className="error-message-box">
              <div className="error-label">Error Message:</div>
              <code className="error-message">{error.toString()}</code>
            </div>
          )}

          {errorCount > 1 && (
            <div className="error-warning">
              ⚠️ This tab has crashed {errorCount} times this session. There may be a persistent issue.
            </div>
          )}

          <div className="error-actions">
            <button onClick={this.handleReset} className="error-btn primary">
              🔄 Try Again
            </button>
            <button
              onClick={() => window.location.reload()}
              className="error-btn secondary"
            >
              Reload Page
            </button>
          </div>

          {errorInfo && (
            <details className="error-stack-details">
              <summary className="error-stack-summary">
                🔍 Component Stack Trace
              </summary>
              <pre className="error-stack">
                {errorInfo.componentStack}
              </pre>
            </details>
          )}

          {error && error.stack && (
            <details className="error-stack-details">
              <summary className="error-stack-summary">
                🐛 Full Error Stack
              </summary>
              <pre className="error-stack">
                {error.stack}
              </pre>
            </details>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

export default AdminErrorBoundary;
