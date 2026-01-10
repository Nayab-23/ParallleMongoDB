// src/pages/OAuthAuthorize.jsx
import { useEffect, useState, useCallback } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { API_BASE_URL } from "../config";
import "./OAuthAuthorize.css";

const DEFAULT_SCOPES = [
  { id: "tasks:read", label: "View your tasks", description: "Read task titles, status, and assignments" },
  { id: "chats:read", label: "View assistant conversations", description: "Read chat history with Parallel" },
  { id: "messages:read", label: "View message content", description: "Read full message text in chats" },
];

const APP_INFO = {
  name: "Parallel VS Code",
  icon: "💻",
  publisher: "Parallel",
  description: "AI-powered coding assistant with workspace context",
};

function parseScopes(scopeParam) {
  if (!scopeParam) return DEFAULT_SCOPES.map((s) => s.id);
  return scopeParam.split(/[\s,]+/).filter(Boolean);
}

function getScopeInfo(scopeId) {
  const found = DEFAULT_SCOPES.find((s) => s.id === scopeId);
  if (found) return found;
  // Fallback for unknown scopes
  return { id: scopeId, label: scopeId.replace(/[_:]/g, " "), description: "" };
}

export default function OAuthAuthorize() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [authState, setAuthState] = useState("checking"); // checking | needsLogin | ready | approving | success | error
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");
  const [countdown, setCountdown] = useState(3);

  // OAuth params
  const clientId = searchParams.get("client_id") || "";
  const redirectUri = searchParams.get("redirect_uri") || "";
  const state = searchParams.get("state") || "";
  const scopeParam = searchParams.get("scope") || "";
  const responseType = searchParams.get("response_type") || "";
  const codeChallenge = searchParams.get("code_challenge") || "";
  const codeChallengeMethod = searchParams.get("code_challenge_method") || "";
  const workspaceId = searchParams.get("workspace_id") || "";
  const queryError = searchParams.get("error") || "";
  const queryErrorDescription = searchParams.get("error_description") || "";

  const scopes = parseScopes(scopeParam);
  const missingParams = [
    ["client_id", clientId],
    ["redirect_uri", redirectUri],
    ["response_type", responseType],
    ["state", state],
    ["code_challenge", codeChallenge],
    ["code_challenge_method", codeChallengeMethod],
  ]
    .filter(([, value]) => !value)
    .map(([key]) => key);
  const hasMissingParams = missingParams.length > 0;
  const hasQueryError = Boolean(queryError || queryErrorDescription);

  // Check if user is logged in
  useEffect(() => {
    if (hasMissingParams) {
      return;
    }
    let cancelled = false;

    const checkAuth = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/me`, {
          credentials: "include",
        });

        if (!res.ok) {
          if (!cancelled) {
            setAuthState("needsLogin");
          }
          return;
        }

        const data = await res.json();
        if (!cancelled) {
          setUser(data);
          setAuthState("ready");
        }
      } catch (err) {
        console.error("Auth check failed", err);
        if (!cancelled) {
          setAuthState("needsLogin");
        }
      }
    };

    checkAuth();
    return () => {
      cancelled = true;
    };
  }, [hasMissingParams]);

  // Countdown after success
  useEffect(() => {
    if (authState !== "success") return;

    const timer = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          clearInterval(timer);
          // If we have a redirect URI, go there
          if (redirectUri) {
            window.location.href = redirectUri;
          }
          return 0;
        }
        return c - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [authState, redirectUri]);

  useEffect(() => {
    if (authState !== "needsLogin" || hasMissingParams || hasQueryError) {
      return;
    }
    const returnUrl = window.location.href;
    sessionStorage.setItem("oauth_return_url", returnUrl);
    navigate(`/app?return_to=${encodeURIComponent(returnUrl)}`, { replace: true });
  }, [authState, hasMissingParams, hasQueryError, navigate]);

  const handleApprove = useCallback(async () => {
    setAuthState("approving");
    setError("");

    try {
      const authorizeUrl = new URL(`${API_BASE_URL}/api/oauth/authorize`);
      authorizeUrl.searchParams.set("client_id", clientId);
      authorizeUrl.searchParams.set("redirect_uri", redirectUri);
      authorizeUrl.searchParams.set("response_type", responseType);
      authorizeUrl.searchParams.set("scope", scopeParam || scopes.join(" "));
      authorizeUrl.searchParams.set("state", state);
      authorizeUrl.searchParams.set("code_challenge", codeChallenge);
      authorizeUrl.searchParams.set("code_challenge_method", codeChallengeMethod);
      if (workspaceId) {
        authorizeUrl.searchParams.set("workspace_id", workspaceId);
      }
      window.location.href = authorizeUrl.toString();
    } catch (err) {
      console.error("OAuth approve failed", err);
      setError(err.message || "Failed to authorize. Please try again.");
      setAuthState("ready");
    }
  }, [
    clientId,
    redirectUri,
    state,
    scopes,
    responseType,
    scopeParam,
    codeChallenge,
    codeChallengeMethod,
    workspaceId,
  ]);

  const handleCancel = useCallback(() => {
    // If we have a redirect URI, go back with error
    if (redirectUri) {
      const url = new URL(redirectUri);
      url.searchParams.set("error", "access_denied");
      url.searchParams.set("error_description", "User cancelled authorization");
      if (state) url.searchParams.set("state", state);
      window.location.href = url.toString();
      return;
    }

    // Otherwise navigate to app
    navigate("/app/vscode");
  }, [redirectUri, state, navigate]);

  const handleLogin = useCallback(() => {
    // Store current URL to return after login
    const returnUrl = window.location.href;
    sessionStorage.setItem("oauth_return_url", returnUrl);
    navigate(`/app?return_to=${encodeURIComponent(returnUrl)}`);
  }, [navigate]);

  const handleRetry = useCallback(() => {
    const nextParams = new URLSearchParams(searchParams.toString());
    nextParams.delete("error");
    nextParams.delete("error_description");
    const nextQuery = nextParams.toString();
    navigate(`/vscode/connect${nextQuery ? `?${nextQuery}` : ""}`, { replace: true });
  }, [searchParams, navigate]);

  const handleBackToSettings = useCallback(() => {
    navigate("/app/vscode");
  }, [navigate]);

  const errorTitleMap = {
    access_denied: "Authorization denied",
    invalid_request: "Invalid authorization request",
    unauthorized_client: "Unauthorized client",
    invalid_scope: "Invalid scope",
    server_error: "Server error",
    temporarily_unavailable: "Service temporarily unavailable",
  };
  const queryErrorTitle =
    errorTitleMap[String(queryError).toLowerCase()] || "Authorization failed";
  const queryErrorMessage =
    queryErrorDescription ||
    "We couldn't complete the authorization. Please try again.";
  const missingParamList = missingParams.join(", ");

  const queryErrorBlock = hasQueryError ? (
    <div className="oauth-error-block">
      <div className="oauth-error-title">{queryErrorTitle}</div>
      <div className="oauth-error-desc">{queryErrorMessage}</div>
      <button className="oauth-button ghost" onClick={handleRetry}>
        Try again
      </button>
    </div>
  ) : null;

  if (hasMissingParams) {
    return (
      <div className="oauth-container">
        <motion.div
          className="oauth-card glass"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <div className="oauth-header">
            <div className="oauth-app-icon">{APP_INFO.icon}</div>
            <h2>Authorization link incomplete</h2>
            <p className="oauth-subtitle">
              This link is missing required details from VS Code. Please restart the sign-in flow from the extension.
            </p>
          </div>

          <div className="oauth-error-block">
            <div className="oauth-error-title">Missing parameters</div>
            <div className="oauth-error-desc">{missingParamList}</div>
          </div>

          <div className="oauth-actions">
            <button className="oauth-button primary" onClick={handleBackToSettings}>
              Go to VS Code settings
            </button>
          </div>
        </motion.div>
      </div>
    );
  }

  // Checking state
  if (authState === "checking") {
    return (
      <div className="oauth-container">
        <motion.div
          className="oauth-card glass"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
        >
          <div className="oauth-loading">
            <div className="oauth-spinner" />
            <p>Checking authentication...</p>
          </div>
        </motion.div>
      </div>
    );
  }

  // Need to login first
  if (authState === "needsLogin") {
    return (
      <div className="oauth-container">
        <motion.div
          className="oauth-card glass"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          {queryErrorBlock}
          <div className="oauth-header">
            <div className="oauth-app-icon">{APP_INFO.icon}</div>
            <h2>Sign in required</h2>
            <p className="oauth-subtitle">
              Sign in to Parallel to authorize {APP_INFO.name}
            </p>
          </div>

          <button className="oauth-button primary" onClick={handleLogin}>
            Sign in to Parallel
          </button>

          <button className="oauth-button ghost" onClick={handleCancel}>
            Cancel
          </button>
        </motion.div>
      </div>
    );
  }

  // Success state
  if (authState === "success") {
    return (
      <div className="oauth-container">
        <motion.div
          className="oauth-card glass"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
        >
          <div className="oauth-success">
            <div className="oauth-success-icon">✓</div>
            <h2>Authorization successful</h2>
            <p className="oauth-subtitle">
              Returning to VS Code{countdown > 0 ? ` in ${countdown}...` : "..."}
            </p>
            <div className="oauth-success-hint">
              You can close this tab if it doesn't redirect automatically.
            </div>
          </div>
        </motion.div>
      </div>
    );
  }

  // Main approval screen
  return (
    <div className="oauth-container">
      <motion.div
        className="oauth-card glass"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        {queryErrorBlock}
        <div className="oauth-header">
          <div className="oauth-app-icon">{APP_INFO.icon}</div>
          <h2>Authorize {APP_INFO.name}</h2>
          <p className="oauth-subtitle">
            {APP_INFO.name} by <strong>{APP_INFO.publisher}</strong> wants to access your Parallel account
          </p>
        </div>

        <div className="oauth-user-badge">
          <span className="oauth-user-avatar">
            {(user?.name || user?.email || "U")[0].toUpperCase()}
          </span>
          <div className="oauth-user-info">
            <div className="oauth-user-name">{user?.name || "User"}</div>
            <div className="oauth-user-email">{user?.email}</div>
          </div>
        </div>

        <div className="oauth-permissions">
          <div className="oauth-permissions-header">
            <span className="oauth-permissions-icon">🔐</span>
            <span>This will allow {APP_INFO.name} to:</span>
          </div>
          <ul className="oauth-scopes-list">
            {scopes.map((scopeId) => {
              const scope = getScopeInfo(scopeId);
              return (
                <li key={scopeId} className="oauth-scope-item">
                  <span className="oauth-scope-check">✓</span>
                  <div>
                    <div className="oauth-scope-label">{scope.label}</div>
                    {scope.description && (
                      <div className="oauth-scope-desc">{scope.description}</div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="oauth-notice">
          <span className="oauth-notice-icon">ℹ️</span>
          <span>
            VS Code cannot write files without explicit confirmation in your editor.
            You can revoke access anytime from Settings.
          </span>
        </div>

        {error && <div className="oauth-error">{error}</div>}

        <div className="oauth-actions">
          <button
            className="oauth-button primary"
            onClick={handleApprove}
            disabled={authState === "approving" || hasQueryError}
          >
            {authState === "approving" ? (
              <>
                <span className="oauth-button-spinner" />
                Authorizing...
              </>
            ) : (
              "Authorize"
            )}
          </button>
          <button
            className="oauth-button ghost"
            onClick={handleCancel}
            disabled={authState === "approving"}
          >
            Cancel
          </button>
        </div>

        <div className="oauth-footer">
          <p>
            By authorizing, you agree to Parallel's{" "}
            <a href="https://parallelos.ai/terms" target="_blank" rel="noopener noreferrer">
              Terms of Service
            </a>{" "}
            and{" "}
            <a href="https://parallelos.ai/privacy" target="_blank" rel="noopener noreferrer">
              Privacy Policy
            </a>
          </p>
        </div>
      </motion.div>
    </div>
  );
}




