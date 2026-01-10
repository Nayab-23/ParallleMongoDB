// src/components/auth/AuthErrorBoundary.jsx
import { Component } from "react";

/**
 * Error boundary for auth-related pages.
 * Catches rendering errors and displays a friendly error page.
 */
export class AuthErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("Auth error boundary caught error:", error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  handleGoHome = () => {
    window.location.href = "/";
  };

  render() {
    if (this.state.hasError) {
      return (
        <div style={styles.container}>
          <div style={styles.card}>
            <div style={styles.icon}>⚠️</div>
            <h2 style={styles.title}>Something went wrong</h2>
            <p style={styles.message}>
              We encountered an error while processing your request.
              Please try again or contact support if the problem persists.
            </p>
            {this.state.error?.message && (
              <pre style={styles.errorDetail}>
                {this.state.error.message}
              </pre>
            )}
            <div style={styles.actions}>
              <button style={styles.primaryButton} onClick={this.handleRetry}>
                Try Again
              </button>
              <button style={styles.ghostButton} onClick={this.handleGoHome}>
                Go Home
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

const styles = {
  container: {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px",
    background: "var(--bg, #0d1117)",
  },
  card: {
    maxWidth: "420px",
    padding: "32px",
    borderRadius: "16px",
    background: "var(--surface, rgba(22, 27, 34, 0.95))",
    border: "1px solid var(--border, rgba(48, 54, 61, 0.8))",
    textAlign: "center",
  },
  icon: {
    fontSize: "48px",
    marginBottom: "16px",
  },
  title: {
    fontSize: "20px",
    fontWeight: "600",
    color: "var(--text, #f0f6fc)",
    margin: "0 0 12px",
  },
  message: {
    fontSize: "14px",
    color: "var(--text-muted, #8b949e)",
    lineHeight: "1.6",
    margin: "0 0 20px",
  },
  errorDetail: {
    fontSize: "12px",
    color: "#f85149",
    background: "rgba(248, 81, 73, 0.1)",
    border: "1px solid rgba(248, 81, 73, 0.3)",
    borderRadius: "8px",
    padding: "12px",
    marginBottom: "20px",
    textAlign: "left",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    maxHeight: "120px",
    overflow: "auto",
  },
  actions: {
    display: "flex",
    flexDirection: "column",
    gap: "10px",
  },
  primaryButton: {
    padding: "12px 20px",
    fontSize: "15px",
    fontWeight: "600",
    borderRadius: "8px",
    border: "none",
    background: "linear-gradient(135deg, #238636 0%, #2ea043 100%)",
    color: "white",
    cursor: "pointer",
  },
  ghostButton: {
    padding: "12px 20px",
    fontSize: "15px",
    fontWeight: "500",
    borderRadius: "8px",
    border: "1px solid var(--border, rgba(48, 54, 61, 0.8))",
    background: "transparent",
    color: "var(--text-muted, #8b949e)",
    cursor: "pointer",
  },
};

export default AuthErrorBoundary;







