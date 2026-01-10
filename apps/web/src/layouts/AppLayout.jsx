// src/layouts/AppLayout.jsx
import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion as Motion } from "framer-motion";
import { API_BASE_URL } from '../config';

import Dashboard from "../pages/Dashboard";
import Login from "../pages/Login";
import Signup from "../pages/Signup";
import ForgotPassword from "../pages/ForgotPassword";
import JoinWorkspace from "../pages/JoinWorkspace";

const ADMIN_EMAILS = [
  "sev777spag3@yahoo.com",
  "severin.spagnola@sjsu.edu",
  "minecraftseverin@gmail.com",
];

export default function AppLayout() {
  // authState: "checking" | "unauth" | "needsOrg" | "ready" | "error"
  const [authState, setAuthState] = useState("checking");
  const [user, setUser] = useState(null);
  const [authError, setAuthError] = useState("");
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const isAdmin = ADMIN_EMAILS.includes((user?.email || "").toLowerCase());

  // which auth screen to show when unauth
  const [page, setPage] = useState("login"); // "login" | "signup" | "forgot"

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const returnTo = params.get("return_to");
    if (!returnTo) {
      return;
    }
    try {
      const target = new URL(returnTo, window.location.origin);
      const apiOrigin = new URL(API_BASE_URL, window.location.origin).origin;
      if (target.origin === window.location.origin || target.origin === apiOrigin) {
        sessionStorage.setItem("oauth_return_url", target.toString());
      }
    } catch {
      // ignore invalid return URL
    }
  }, []);

  const loadBootstrap = useCallback(async () => {
    const maxRetries = 3;
    let attempt = 0;

    while (attempt < maxRetries) {
      try {
        console.log(`[Bootstrap] Attempt ${attempt + 1}/${maxRetries} - Calling ${API_BASE_URL}/api/v1/bootstrap`);
        const controller = new AbortController();
        const timeoutId = setTimeout(() => {
          console.warn(`[Bootstrap] ⏰ Request timeout after 30s`);
          controller.abort();
        }, 30000);

        const startTime = Date.now();
        let response = await fetch(`${API_BASE_URL}/api/v1/bootstrap`, {
          credentials: "include",
          signal: controller.signal,
        });

        const elapsed = Date.now() - startTime;
        console.log(`[Bootstrap] ✅ /api/v1/bootstrap responded in ${elapsed}ms with status ${response.status}`);

        // Fallback if bootstrap endpoint isn't available
        if (response.status === 404) {
          console.log(`[Bootstrap] Bootstrap endpoint not found, trying /api/me fallback`);
          clearTimeout(timeoutId);
          const fallbackStart = Date.now();
          response = await fetch(`${API_BASE_URL}/api/me`, {
            credentials: "include",
            signal: controller.signal,
          });
          const fallbackElapsed = Date.now() - fallbackStart;
          console.log(`[Bootstrap] ✅ /api/me responded in ${fallbackElapsed}ms with status ${response.status}`);
        }

        clearTimeout(timeoutId);

        // If 401 or 403, user is not authenticated - don't retry, just redirect to login
        if (response.status === 401 || response.status === 403) {
          console.log(`[Bootstrap] 🚫 Not authenticated (${response.status}), showing login`);
          const error = new Error("Not authenticated");
          error.status = response.status;
          error.requiresAuth = true;
          throw error;
        }

        if (!response.ok) {
          const errorBody = await response.text();
          console.error(`[Bootstrap] ❌ Request failed with ${response.status}:`, errorBody);
          throw new Error(`Bootstrap failed: ${response.status}`);
        }

        const data = await response.json();
        console.log("[Bootstrap] 🎉 Success - Full response:");
        console.log(JSON.stringify(data, null, 2));
        return data;
      } catch (error) {
        // If it's an auth error, don't retry - go straight to login
        if (error.requiresAuth || error.status === 401 || error.status === 403) {
          throw error;
        }

        if (error.name === 'AbortError') {
          console.error(`[Bootstrap] ⏰ Request timed out after 30s`);
        }

        attempt += 1;
        console.error(`[Bootstrap] ❌ Attempt ${attempt} failed:`, error);
        if (attempt >= maxRetries) {
          throw new Error("Failed to load workspace after 3 attempts");
        }
        console.log(`[Bootstrap] 🔄 Retrying in 2s...`);
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      setAuthError("");
      try {
        const data = await loadBootstrap();
        if (cancelled) return;
        let userData = data?.user || data?.me || data;
        if (!userData) {
          throw new Error("Bootstrap response missing user");
        }

        const userEmail = userData.email || "";
        const isUserAdmin = ADMIN_EMAILS.includes(userEmail.toLowerCase());
        console.log("[Bootstrap] 📋 User data from bootstrap:", {
          email: userEmail,
          org_id: userData.org_id,
          workspaces: data?.workspaces?.length,
          isAdmin: isUserAdmin
        });

        // If org_id is missing, fetch from /api/me to get complete user data
        if (!userData.org_id) {
          console.log("[Bootstrap] ⚠️ org_id missing from bootstrap, fetching from /api/me...");
          try {
            const meResponse = await fetch(`${API_BASE_URL}/api/me`, {
              credentials: "include",
            });
            if (meResponse.ok) {
              const meData = await meResponse.json();
              console.log("[Bootstrap] ✅ /api/me returned:", { org_id: meData.org_id, email: meData.email });
              // Merge the data, preferring /api/me for org_id
              userData = { ...userData, ...meData };
            }
          } catch (err) {
            console.warn("[Bootstrap] Failed to fetch /api/me:", err);
          }
        }

        setUser(userData);

        if (!userData.org_id) {
          console.log("[Bootstrap] ⚠️ Still no org_id after /api/me check", {
            isAdmin: isUserAdmin,
            willStartPolling: isUserAdmin
          });
          setAuthState("needsOrg");
        } else {
          console.log("[Bootstrap] ✅ Has org_id, setting authState to ready");
          setAuthState("ready");
        }
      } catch (err) {
        if (cancelled) return;
        console.error("[Bootstrap] Final failure:", err);

        // If it's an auth error (401/403), show login instead of error page
        if (err.requiresAuth || err.status === 401 || err.status === 403) {
          console.log("[Bootstrap] Auth required, redirecting to login");
          setAuthState("unauth");
        } else {
          setAuthError(err?.message || "Failed to load workspace.");
          setAuthState("error");
        }
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [loadBootstrap, bootstrapAttempt]);

  useEffect(() => {
    if (!user) return;

    const detectAndSetTimezone = async () => {
      try {
        const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        if (!userTimezone) return;

        const cacheKey = `timezone_sent_${user.id}`;
        const cached = localStorage.getItem(cacheKey);
        if (cached === userTimezone) return;

        console.log("[Timezone] Detected:", userTimezone);

        const response = await fetch(`${API_BASE_URL}/api/settings/timezone`, {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ timezone: userTimezone }),
        });

        if (response.ok) {
          console.log("[Timezone] ✅ Set to:", userTimezone);
          localStorage.setItem(cacheKey, userTimezone);
        } else {
          console.warn("[Timezone] Failed to set:", response.status);
        }
      } catch (err) {
        console.error("[Timezone] Failed to set:", err);
      }
    };

    detectAndSetTimezone();
  }, [user]);

  useEffect(() => {
    if (authState !== "ready") {
      return;
    }
    const returnUrl = sessionStorage.getItem("oauth_return_url");
    if (!returnUrl) {
      return;
    }
    sessionStorage.removeItem("oauth_return_url");
    try {
      const target = new URL(returnUrl, window.location.origin);
      const apiOrigin = new URL(API_BASE_URL, window.location.origin).origin;
      if (target.origin === window.location.origin || target.origin === apiOrigin) {
        window.location.href = target.toString();
      }
    } catch {
      // ignore invalid return URL
    }
  }, [authState]);

  const go = (to) => {
    setPage(to);
  };

  // After login/signup, we want to re-run the /me logic,
  // so instead of forcing "dashboard" just reload /app.
  const goDashboard = () => {
    window.location.reload();
  };

  // If an admin has no org yet, poll /api/me until backend creates it
  useEffect(() => {
    if (!isAdmin || user?.org_id || authState !== "needsOrg") {
      console.log("[Polling] Skipping org poll:", { isAdmin, hasOrgId: !!user?.org_id, authState });
      return;
    }

    console.log("[Polling] Starting org poll for admin without org_id");
    const pollForOrg = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/me`, {
          credentials: "include",
        });
        if (!res.ok) {
          console.log("[Polling] Poll returned non-OK status:", res.status);
          return;
        }
        const updatedUser = await res.json();
        console.log("[Polling] Poll result:", { org_id: updatedUser?.org_id, email: updatedUser?.email });
        if (updatedUser?.org_id) {
          console.log("[Polling] 🎉 Org detected! Will reload in 3 seconds to show logs...");
          setUser(updatedUser);
          clearInterval(pollForOrg);

          // Delay reload so logs are visible
          setTimeout(() => {
            console.log("[Polling] 🔄 Reloading page now");
            window.location.reload();
          }, 3000);
        }
      } catch (err) {
        console.error("[Polling] ❌ Error polling for org:", err);
      }
    }, 1000);

    const timeout = setTimeout(() => {
      console.log("[Polling] Timeout after 10s, stopping poll");
      clearInterval(pollForOrg);
    }, 10000);
    return () => {
      clearInterval(pollForOrg);
      clearTimeout(timeout);
    };
  }, [authState, isAdmin, user?.org_id]);

  if (authState === "checking") {
    return (
      <div
        style={{
          display: "flex",
          height: "100vh",
          alignItems: "center",
          justifyContent: "center",
          flexDirection: "column",
          gap: "12px",
        }}
      >
        <span>Loading workspace…</span>
        <span style={{ fontSize: "13px", color: "#6b7280" }}>
          Authenticating user
        </span>
      </div>
    );
  }

  if (authState === "error") {
    return (
      <div
        style={{
          display: "flex",
          height: "100vh",
          alignItems: "center",
          justifyContent: "center",
          flexDirection: "column",
          gap: "12px",
          textAlign: "center",
          padding: "24px",
        }}
      >
        <span style={{ fontSize: "16px", fontWeight: 600 }}>
          Failed to load workspace
        </span>
        <span style={{ fontSize: "13px", color: "#6b7280" }}>
          {authError || "Authentication or bootstrap failed. Please retry."}
        </span>
        <button
          style={{
            marginTop: "8px",
            padding: "10px 14px",
            background: "#2563eb",
            color: "white",
            border: "none",
            borderRadius: "6px",
            cursor: "pointer",
            fontWeight: 600,
          }}
          onClick={() => {
            setAuthState("checking");
            setAuthError("");
            setBootstrapAttempt((k) => k + 1);
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  let content = null;

  if (authState === "unauth") {
    // not logged in – show auth stack
    if (page === "signup") {
      content = <Signup goLogin={() => go("login")} goDashboard={goDashboard} />;
    } else if (page === "forgot") {
      content = <ForgotPassword goLogin={() => go("login")} />;
    } else {
      content = (
        <Login
          goSignup={() => go("signup")}
          goForgot={() => go("forgot")}
          goDashboard={goDashboard}
        />
      );
    }
  } else if (authState === "needsOrg") {
    if (!user?.org_id && !isAdmin) {
      // logged in, but not yet in an organization
      content = <JoinWorkspace user={user} onJoined={goDashboard} />;
    } else if (!user?.org_id && isAdmin) {
      // admin with no org yet — backend should auto-create; keep polling
      content = (
        <div
          style={{
            display: "flex",
            height: "100vh",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <span>Setting up your workspace…</span>
        </div>
      );
    }
  } else if (authState === "ready") {
    // fully authenticated and activated
    content = <Dashboard user={user} />;
  }

  return (
    <AnimatePresence mode="wait">
      <Motion.div
        key={`${authState}-${page}`}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -12 }}
        transition={{ duration: 0.28 }}
        style={{ height: "100%" }}
      >
        {content}
      </Motion.div>
    </AnimatePresence>
  );
}
