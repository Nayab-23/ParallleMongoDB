// src/components/ErrorBoundary.jsx
import { Component } from "react";

/**
 * Error Boundary component that catches JavaScript errors in child components.
 * Provides a friendly fallback UI and prevents the whole app from crashing.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("[ErrorBoundary] Caught error:", error, errorInfo);
    this.setState({ errorInfo });

    if (typeof window !== "undefined" && typeof window.__pushBootlog === "function") {
      window.__pushBootlog({
        tag: "error-boundary",
        message: error?.message,
        name: error?.name,
        stack: error?.stack,
        componentStack: errorInfo?.componentStack,
      });
      window.__bootlog?.dump?.("error-boundary", true);
    }
    
    // Optional: Send to error reporting service
    if (typeof this.props.onError === "function") {
      this.props.onError(error, errorInfo);
    }
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    if (typeof this.props.onRetry === "function") {
      this.props.onRetry();
    }
  };

  handleGoHome = () => {
    window.location.href = "/app";
  };

  render() {
    if (this.state.hasError) {
      // Custom fallback UI if provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const isDev = import.meta.env.DEV;
      const errorMessage = this.state.error?.message || "An unexpected error occurred";

      return (
        <div style={styles.container}>
          <div style={styles.card}>
            <div style={styles.iconContainer}>
              <span style={styles.icon}>⚠️</span>
            </div>
            <h1 style={styles.title}>Something went wrong</h1>
            <p style={styles.message}>
              {this.props.message || "We encountered an error loading this page."}
            </p>
            
            {isDev && (
              <details style={styles.details}>
                <summary style={styles.summary}>Error Details (Dev)</summary>
                <pre style={styles.errorText}>{errorMessage}</pre>
                {this.state.errorInfo?.componentStack && (
                  <pre style={styles.stackTrace}>
                    {this.state.errorInfo.componentStack}
                  </pre>
                )}
              </details>
            )}

            <div style={styles.actions}>
              <button style={styles.primaryButton} onClick={this.handleRetry}>
                Try Again
              </button>
              <button style={styles.ghostButton} onClick={this.handleGoHome}>
                Go to Dashboard
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
    background: "linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 50%, #0f0f1a 100%)",
  },
  card: {
    width: "100%",
    maxWidth: "440px",
    padding: "40px",
    borderRadius: "20px",
    background: "rgba(20, 20, 30, 0.85)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    backdropFilter: "blur(20px)",
    boxShadow: "0 24px 48px rgba(0, 0, 0, 0.4)",
    textAlign: "center",
  },
  iconContainer: {
    marginBottom: "20px",
  },
  icon: {
    fontSize: "48px",
  },
  title: {
    fontFamily: "'DM Sans', 'Inter', system-ui, sans-serif",
    fontSize: "1.5rem",
    fontWeight: "600",
    color: "#fff",
    margin: "0 0 12px 0",
    letterSpacing: "-0.02em",
  },
  message: {
    color: "rgba(255, 255, 255, 0.6)",
    fontSize: "0.9375rem",
    lineHeight: "1.5",
    margin: "0 0 24px 0",
  },
  details: {
    textAlign: "left",
    marginBottom: "24px",
    background: "rgba(0, 0, 0, 0.3)",
    borderRadius: "8px",
    padding: "12px",
  },
  summary: {
    cursor: "pointer",
    color: "rgba(255, 255, 255, 0.5)",
    fontSize: "0.8125rem",
    marginBottom: "8px",
  },
  errorText: {
    color: "#f87171",
    fontSize: "0.8125rem",
    margin: "8px 0",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  stackTrace: {
    color: "rgba(255, 255, 255, 0.4)",
    fontSize: "0.75rem",
    margin: "8px 0 0 0",
    maxHeight: "200px",
    overflow: "auto",
    whiteSpace: "pre-wrap",
  },
  actions: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
  primaryButton: {
    width: "100%",
    padding: "14px 24px",
    fontSize: "0.9375rem",
    fontWeight: "500",
    borderRadius: "10px",
    cursor: "pointer",
    background: "linear-gradient(135deg, #007ACC 0%, #1F9CF0 100%)",
    color: "#fff",
    border: "none",
    boxShadow: "0 4px 12px rgba(0, 122, 204, 0.3)",
    transition: "all 0.2s ease",
  },
  ghostButton: {
    width: "100%",
    padding: "14px 24px",
    fontSize: "0.9375rem",
    fontWeight: "500",
    borderRadius: "10px",
    cursor: "pointer",
    background: "transparent",
    color: "rgba(255, 255, 255, 0.7)",
    border: "1px solid rgba(255, 255, 255, 0.12)",
    transition: "all 0.2s ease",
  },
};
