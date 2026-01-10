import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { useNavigate, Link } from "react-router-dom";
import "./Auth.css";
import { API_BASE_URL } from "../config";
import { getIntegrationsStatus, getTimeline } from "../lib/tasksApi";
import Timeline from "../components/brief/Timeline";
import DebugContextModal from "../components/brief/DebugContextModal";
import CompletedSidebar from "../components/brief/CompletedSidebar";

const formatRemaining = (totalSeconds) => {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
};

function formatRelativeTime(isoString) {
  if (!isoString) return "";
  const now = new Date();
  const then = new Date(isoString);
  const diffMs = now - then;
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffHours / 24);

  if (diffHours < 1) return "Just now";
  if (diffHours < 24) return `${diffHours} hours ago`;
  if (diffDays === 1) return "Yesterday";
  return `${diffDays} days ago`;
}

function validateTimelineSchema(timeline) {
  if (!timeline || typeof timeline !== "object") {
    return {};
  }

  const validatedTimeline = { ...timeline };

  for (const timeframe of ["1d", "7d", "28d", "today", "this_week", "this_month"]) {
    const section = validatedTimeline[timeframe];
    if (!section) continue;

    // Check for old schema keys
    const oldKeys = ["critical", "high", "high_priority", "medium", "low", "upcoming", "goals", "milestones"];
    const hasOldSchema = oldKeys.some(key => key in section);
    if (hasOldSchema) {
      console.warn(`⚠️ Timeline has old schema in ${timeframe}:`, Object.keys(section));
    }

    // Ensure new schema keys exist
    if (!("urgent" in section)) section.urgent = [];
    if (!("normal" in section)) section.normal = [];
  }

  return validatedTimeline;
}

export default function DailyBrief({
  onHistoryChange = () => {},
  externalPersonalData = null,
  externalLoading = false,
  externalOnRefresh = null,
  externalRefreshing = false,
  externalReloadCanon = null,
  externalRefreshInterval = null,
  externalLastSync = null,
  onboardingStatus = null,
  onOpenOnboarding = () => {},
}) {
  const navigate = useNavigate();
  const [brief, setBrief] = useState(null);
  const [missing, setMissing] = useState([]);
  const [error, setError] = useState("");
  const [loadingBrief, setLoadingBrief] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [showDebug, setShowDebug] = useState(false);
  const [debugContext] = useState(null);
  const [syncing, setSyncing] = useState(false);
  const userIsActive = useRef(false);
  const lastInteraction = useRef(Date.now());
  const [completedItems, setCompletedItems] = useState([]);
  const [, setCompletingItem] = useState(null);
  const [dismissedItems, setDismissedItems] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [canonicalPlan, setCanonicalPlan] = useState(null);
  const [lastAiSync, setLastAiSync] = useState(null);
  const [lastSync, setLastSync] = useState(null);
  const [refreshIntervalMinutes, setRefreshIntervalMinutes] = useState(1);
  const [timeRemaining, setTimeRemaining] = useState("--:--");

  // useEffect(() => {
  //   console.log("🔴 [TIMELINE] DailyBrief render");
  // }, []);

  const effectiveRefreshInterval =
    externalRefreshInterval !== null && externalRefreshInterval !== undefined
      ? externalRefreshInterval
      : refreshIntervalMinutes;
  const effectiveLastSync =
    externalLastSync !== null && externalLastSync !== undefined
      ? externalLastSync
      : lastSync;

  const isSameItem = (a, b) => {
    if (!a || !b) return false;
    if (a.source_id && b.source_id && a.source_id === b.source_id) return true;
    // Use signature for unique identification instead of title
    if (a.signature && b.signature) return a.signature === b.signature;
    return a.title === b.title && a.source_type === b.source_type;
  };

  // auth gate
  useEffect(() => {
    if (externalPersonalData) return;
    const loadMe = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/me`, {
          credentials: "include",
        });
        if (!res.ok) throw new Error("Not authenticated");
        const data = await res.json();
        const intervalPref = data?.preferences?.canon_refresh_interval_minutes;
        const parsed = Number(intervalPref);
        if (!Number.isNaN(parsed)) {
          setRefreshIntervalMinutes(parsed);
        }
      } catch (err) {
        console.error("Failed to load user", err);
        // DEV MODE: Don't redirect to login
        // navigate("/login");
      }
    };
    loadMe();
  }, [navigate, externalPersonalData]);

  const loadBrief = useCallback(async () => {
    if (externalPersonalData) {
      setLoadingBrief(false);
      return;
    }
    setLoadingBrief(true);
    setError("");
    setMissing([]);
    try {
      const data = await getTimeline();

      const dailyGoals = Array.isArray(data?.daily_goals)
        ? { normal: data.daily_goals }
        : data?.daily_goals || {};
      const weeklyFocus = Array.isArray(data?.weekly_focus)
        ? { normal: data.weekly_focus }
        : data?.weekly_focus || {};
      const monthlyObjectives = Array.isArray(data?.monthly_objectives)
        ? { normal: data.monthly_objectives }
        : data?.monthly_objectives || {};

      const timeline = validateTimelineSchema({
        "1d": Object.keys(dailyGoals).length ? dailyGoals : data?.timeline?.["1d"] || {},
        "7d": Object.keys(weeklyFocus).length ? weeklyFocus : data?.timeline?.["7d"] || {},
        "28d": Object.keys(monthlyObjectives).length ? monthlyObjectives : data?.timeline?.["28d"] || {},
      });

      const canonPersonal = {
        timeline,
        priorities: data?.priorities || [],
        integrations: data?.integrations || {},
        data_stale: data?.data_stale || false,
        needs_reconnect: data?.needs_reconnect || false,
        last_sync: data?.last_sync || data?.last_ai_sync || null,
      };

      setCanonicalPlan({ personal: canonPersonal });
      setLastAiSync(data?.last_ai_sync || null);
      setLastSync(data?.last_sync || data?.last_ai_sync || null);
      setBrief({ personal: canonPersonal });
      setSyncing(false);
      setLoadingBrief(false);
    } catch (err) {
      console.error("Failed to fetch brief:", err);
      setError(
        "Could not load your daily brief. Ensure Gmail and Calendar are connected in Settings."
      );
      setLoadingBrief(false);
      setSyncing(false);
    }
  }, [externalPersonalData]);

  const loadStatus = useCallback(async () => {
    if (externalPersonalData) return;
    setLoadingStatus(true);
    setError("");
    setMissing([]);
    try {
      const data = await getIntegrationsStatus();
      
      // DEV MODE: Handle null data gracefully
      if (!data) {
        // console.log("[DailyBrief] No integration status (dev mode), proceeding without integrations");
        setMissing([]);
        await loadBrief();
        return;
      }
      
      const missingList = [];
      if (!(data.gmail?.connected || data.google_gmail?.connected)) {
        missingList.push("Gmail");
      }
      if (!(data.calendar?.connected || data.google_calendar?.connected)) {
        missingList.push("Calendar");
      }
      setMissing(missingList);
      if (missingList.length === 0) {
        await loadBrief();
      } else {
        setBrief(null);
      }
    } catch (err) {
      console.error("Integration status failed", err);
      // DEV MODE: Don't show error, just proceed
      setMissing([]);
      await loadBrief();
    } finally {
      setLoadingStatus(false);
    }
  }, [externalPersonalData, loadBrief]);

  const handleComplete = async (item) => {
    if (!item) return;
    setCompletingItem(item);
    await new Promise((resolve) => setTimeout(resolve, 600));
    try {
      await fetch(`${API_BASE_URL}/api/brief/items/complete`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          signature: item.signature || item.source_id || item.id || item.title,
          title: item.title,
          source_id: item.source_id,
          source_type: item.source_type,
        }),
      });
      setCompletedItems((prev) => [item, ...prev]);
      setDismissedItems((prev) => [...prev, item]);
      setTimeout(() => {
        if (externalReloadCanon) {
          externalReloadCanon();
        } else {
          loadBrief();
        }
      }, 300);
      onHistoryChange();
    } catch (err) {
      console.error("Failed to mark complete:", err);
    } finally {
      setCompletingItem(null);
    }
  };

  const handleDelete = (item) => {
    if (!item) return;

    // Optimistically add to dismissed items (using signature for unique matching)
    setDismissedItems((prev) => [...prev, item]);

    const deleteItem = async () => {
      try {
        const signature = item.signature || item.source_id || item.id || item.title;
        if (!signature) return;

        // Delete the item
        await fetch(`${API_BASE_URL}/api/brief/items/delete`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            signature,
            title: item.title  // Send title for pattern tracking
          }),
        });

        // Check for deletion pattern (3-strike system)
        if (item.title) {
          try {
            const patternResponse = await fetch(
              `${API_BASE_URL}/api/brief/check-deletion-pattern?title=${encodeURIComponent(item.title)}`,
              { credentials: 'include' }
            );

            if (patternResponse.ok) {
              const pattern = await patternResponse.json();

              console.log('[Delete Pattern]', pattern);

              // If should prompt (≥3 deletions + ≥80% deletion rate)
              if (pattern.should_prompt) {
                const confirmed = window.confirm(
                  `📊 Deletion Pattern Detected\n\n` +
                  `You've deleted "${item.title}" ${pattern.deletion_count} times ` +
                  `(${Math.round(pattern.deletion_rate * 100)}% deletion rate).\n\n` +
                  `Would you like to HIDE all future "${item.title}" events?\n\n` +
                  `You can always re-enable them in Settings → Filtered Events.`
                );

                if (confirmed) {
                  // Add to filter list
                  const filterResponse = await fetch(`${API_BASE_URL}/api/brief/filter-event`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      title: item.title,
                      filter: true
                    }),
                    credentials: 'include',
                  });

                  if (filterResponse.ok) {
                    alert(
                      `✅ Filter Applied\n\n` +
                      `All "${item.title}" events will now be hidden.\n\n` +
                      `Manage filters in Settings → Filtered Events.`
                    );
                  }
                }
              }
            }
          } catch (patternErr) {
            // Don't fail the whole delete if pattern check fails
            console.error('[Pattern Check Error]', patternErr);
          }
        }

        setTimeout(() => {
          if (externalReloadCanon) {
            externalReloadCanon();
          } else {
            loadBrief();
          }
        }, 300);
        onHistoryChange();
      } catch (err) {
        console.error("Failed to delete item:", err);
      }
    };
    deleteItem();
  };

  const handleUndo = (item) => {
    setCompletedItems((prev) => prev.filter((c) => !isSameItem(c, item)));
    setDismissedItems((prev) => prev.filter((c) => !isSameItem(c, item)));
  };

  const handleTimelineRefresh = () => {
    if (externalOnRefresh) {
      externalOnRefresh();
    } else {
      loadBrief();
    }
  };

  const fetchDebugContext = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/brief/debug-context`, {
        method: "GET",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      // console.log("🔍 DEBUG CONTEXT:", data);

      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `debug-context-${Date.now()}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      alert("Debug context downloaded! Check your Downloads folder.");
    } catch (err) {
      console.error("Failed to fetch debug context:", err);
      alert("Failed to load debug context. Check console for details.");
    }
  };

  useEffect(() => {
    if (externalPersonalData) return;
    loadStatus();
  }, [externalPersonalData, loadStatus]);

  useEffect(() => {
    if (effectiveRefreshInterval === 0) {
      setTimeRemaining("Off");
      return;
    }

    if (!effectiveRefreshInterval || !effectiveLastSync) {
      setTimeRemaining("--:--");
      return;
    }

    const updateRemaining = () => {
      const lastSyncMs = new Date(effectiveLastSync).getTime();
      if (!lastSyncMs || Number.isNaN(lastSyncMs)) {
        setTimeRemaining("--:--");
        return;
      }

      const intervalSeconds = Number(effectiveRefreshInterval) * 60;
      const elapsedSeconds = Math.floor((Date.now() - lastSyncMs) / 1000);
      const remainingSeconds = Math.max(0, intervalSeconds - elapsedSeconds);
      setTimeRemaining(formatRemaining(remainingSeconds));
    };

    updateRemaining();
    const timer = setInterval(updateRemaining, 1000);
    return () => clearInterval(timer);
  }, [effectiveRefreshInterval, effectiveLastSync]);

  const isDismissed = useCallback(
    (item) => dismissedItems.some((d) => isSameItem(d, item)),
    [dismissedItems]
  );

  const activeBrief = externalPersonalData ? { personal: externalPersonalData } : canonicalPlan || brief;
  const personalData = useMemo(
    () =>
      externalPersonalData ||
      canonicalPlan?.personal ||
      canonicalPlan ||
      brief?.personal ||
      {},
    [externalPersonalData, canonicalPlan, brief]
  );

  const filterList = useCallback(
    (list) => (Array.isArray(list) ? list.filter((i) => !isDismissed(i)) : []),
    [isDismissed]
  );

  const filteredTimeline = useMemo(() => {
    const tl = personalData?.timeline || {};
    const keys = ["1d", "7d", "28d"];
    const out = {};
    keys.forEach((k) => {
      const section = tl[k];
      if (!section) return;
      const filtered = {};
      Object.entries(section).forEach(([key, val]) => {
        filtered[key] = Array.isArray(val) ? filterList(val) : val;
      });
      out[k] = filtered;
    });
    return out;
  }, [personalData, filterList]);

  const filteredPersonal = useMemo(() => {
    const p = personalData || {};
    const result = {
      ...p,
      priorities: filterList(p.priorities),
      unread_emails: filterList(p.unread_emails),
      upcoming_meetings: filterList(p.upcoming_meetings),
      calendar: filterList(p.calendar),
      mentions: filterList(p.mentions),
      actions: filterList(p.actions),
      timeline: filteredTimeline,
    };

    // Debug logging only when there are issues
    // if (result.needs_reconnect || result.data_stale) {
    //   console.log('[DailyBrief] OAuth/Sync Issue Detected:', {
    //     needs_reconnect: result.needs_reconnect,
    //     data_stale: result.data_stale,
    //     integrations: result.integrations,
    //     last_sync: result.last_sync,
    //   });
    // }

    return result;
  }, [personalData, filteredTimeline, filterList]);

  const heroTimeline = useMemo(() => {
    const tl = filteredPersonal?.timeline || {};
    const mapSection = (section) => ({
      urgent: section?.urgent || [],
      normal: section?.normal || [],
    });
    return {
      today: mapSection(tl["1d"] || tl.today || {}),
      this_week: mapSection(tl["7d"] || tl.this_week || {}),
      this_month: mapSection(tl["28d"] || tl.this_month || {}),
    };
  }, [filteredPersonal?.timeline]);
  const hiddenCount = dismissedItems.length;

  // Track user interactions to pause polling while user is active/reading
  useEffect(() => {
    const handleInteraction = () => {
      lastInteraction.current = Date.now();
      userIsActive.current = true;
      setTimeout(() => {
        if (Date.now() - lastInteraction.current > 5000) {
          userIsActive.current = false;
        }
      }, 5000);
    };

    window.addEventListener("click", handleInteraction);
    window.addEventListener("keydown", handleInteraction);
    window.addEventListener("mousemove", handleInteraction);
    window.addEventListener("touchstart", handleInteraction);

    return () => {
      window.removeEventListener("click", handleInteraction);
      window.removeEventListener("keydown", handleInteraction);
      window.removeEventListener("mousemove", handleInteraction);
      window.removeEventListener("touchstart", handleInteraction);
    };
  }, []);

  if (externalLoading && !activeBrief) {
    return <div className="brief-loading">Loading your brief...</div>;
  }
  if (!externalPersonalData) {
    if (loadingBrief && !activeBrief) {
      return <div className="brief-loading">Loading your brief...</div>;
    }
    if (!activeBrief && !loadingBrief) {
      return <div className="brief-loading">Setting up your plan...</div>;
    }
  }

  const formatDate = (str) => {
    if (!str) return "";
    return new Date(str).toLocaleString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  };

  const refreshTimerLabel =
    effectiveRefreshInterval === 0
      ? "Auto-refresh disabled"
      : `Next auto-refresh in: ${timeRemaining}`;

  return (
    <div className="auth-container" style={{ padding: 0 }}>
      {externalRefreshing && (
        <div className="refreshing-indicator">
          <span className="spinner" />
          <span>Refreshing your timeline...</span>
        </div>
      )}
      <div
        className="auth-card glass"
        style={{ width: "100%", maxWidth: 1200, textAlign: "left", padding: 24 }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div>
            <h2 className="auth-title">Daily Brief</h2>
            <p className="auth-subtitle">
              {brief?.date ? brief.date : ""}
              {brief?.generated_at
                ? ` • Generated ${formatDate(brief.generated_at)}`
                : ""}
            </p>
            {lastAiSync && (
              <p className="sync-status">
                Last synced: {formatDistanceToNow(new Date(lastAiSync), { addSuffix: true })}
              </p>
            )}
            <p className="refresh-timer">{refreshTimerLabel}</p>
          </div>
          <div className="brief-actions">
            {syncing && (
              <span className="syncing-badge">
                <span className="spinner" /> Syncing...
              </span>
            )}
            <button
              className="auth-button"
              style={{ width: "auto", padding: "10px 14px" }}
              onClick={() => {
                if (externalOnRefresh) {
                  externalOnRefresh();
                } else {
                  loadBrief();
                }
              }}
              disabled={externalRefreshing || loadingBrief}
            >
              {externalRefreshing || loadingBrief ? "Refreshing…" : "Refresh"}
            </button>
            <button
              className="auth-button"
              style={{
                width: "auto",
                padding: "10px 14px",
                marginLeft: 8,
                background: "linear-gradient(135deg, #ff4757 0%, #ff6348 100%)",
                border: "none"
              }}
              onClick={async () => {
                if (!window.confirm(
                  "⚠️ WARNING: Debug Reset\n\n" +
                  "This will DELETE:\n" +
                  "• All timeline items\n" +
                  "• All completion/deletion history\n" +
                  "• All filter lists\n\n" +
                  "Your timeline will regenerate on next refresh (within 1 minute).\n\n" +
                  "Are you sure you want to continue?"
                )) {
                  return;
                }

                try {
                  const response = await fetch(`${API_BASE_URL}/api/debug/reset-timeline`, {
                    method: 'POST',
                    credentials: 'include',
                  });

                  const data = await response.json();

                  if (response.ok) {
                    alert(
                      `✅ Timeline Reset Complete\n\n` +
                      `Deleted ${data.deleted_items} history items.\n\n` +
                      `${data.next_steps}`
                    );

                    // Clear local state
                    setDismissedItems([]);
                    setCompletedItems([]);

                    // Trigger refresh
                    if (externalOnRefresh) {
                      externalOnRefresh();
                    } else {
                      loadBrief();
                    }
                  } else {
                    alert(`❌ Reset failed: ${data.message || 'Unknown error'}`);
                  }
                } catch (err) {
                  console.error('Debug reset error:', err);
                  alert(`❌ Reset failed: ${err.message}`);
                }
              }}
              title="DEBUG: Reset timeline and deletion history"
            >
              🔄 Debug Reset
            </button>
            <button
              className="auth-button"
              style={{ width: "auto", padding: "10px 14px", marginLeft: 8 }}
              onClick={fetchDebugContext}
              title="Download raw AI context"
            >
              📥 Download Debug
            </button>
          </div>
        </div>

        {error && <div className="auth-status">{error}</div>}
        {loadingStatus && (
          <div className="brief-skeleton">
            <div className="skeleton-bar" />
            <div className="skeleton-grid">
              <div className="skeleton-card" />
              <div className="skeleton-card" />
              <div className="skeleton-card" />
            </div>
          </div>
        )}

        {missing.length > 0 && (
          <div
            style={{
              border: "1px solid var(--border)",
              borderRadius: "12px",
              padding: "12px",
              background: "var(--code-bg)",
              marginTop: 12,
            }}
          >
            <div style={{ fontWeight: 700 }}>Connect your accounts</div>
            <div className="roles" style={{ marginTop: 6 }}>
              You need to connect Gmail and Calendar to enable the Daily Brief.
            </div>
            <div className="roles" style={{ marginTop: 4 }}>
              Missing: {missing.join(", ")}
            </div>
            <div style={{ marginTop: 8 }}>
              <button
                className="auth-button"
                style={{ width: "auto", padding: "10px 14px" }}
                onClick={() => navigate("/settings")}
              >
                Go to Settings
              </button>
              <button
                className="auth-button"
                style={{
                  width: "auto",
                  padding: "10px 14px",
                  marginLeft: 8,
                }}
                onClick={loadStatus}
              >
                Try again
              </button>
            </div>
          </div>
        )}

        {activeBrief && (
          <>
            <div style={{ marginTop: 12 }}>
                {onboardingStatus &&
                  !onboardingStatus.onboarding_complete &&
                  (!onboardingStatus.gmail_connected || !onboardingStatus.calendar_connected) && (
                    <div className="empty-state-banner">
                      <div>
                          <h3>Connect your tools to get started</h3>
                          <p>
                            Parallel needs access to your Gmail and Calendar to create intelligent
                            task recommendations.
                          </p>
                        </div>
                        <button className="link-button" onClick={onOpenOnboarding}>
                          Complete setup →
                        </button>
                      </div>
                    )}

                  {/* OAuth Connection Warning */}
                  {(() => {
                    // Check for integration issues
                    const gmailNeedsReconnect = filteredPersonal?.integrations?.gmail?.needs_reconnect === true;
                    const calendarNeedsReconnect = filteredPersonal?.integrations?.calendar?.needs_reconnect === true;
                    const gmailNotConnected = filteredPersonal?.integrations?.gmail?.connected === false;
                    const calendarNotConnected = filteredPersonal?.integrations?.calendar?.connected === false;

                    const hasIssues =
                      filteredPersonal?.needs_reconnect ||
                      gmailNeedsReconnect ||
                      calendarNeedsReconnect ||
                      gmailNotConnected ||
                      calendarNotConnected;

                    // Calculate stale data check for debugging
                    const lastSyncDate = filteredPersonal?.last_sync ? new Date(filteredPersonal.last_sync) : null;
                    const hoursSinceSync = lastSyncDate ? (Date.now() - lastSyncDate.getTime()) / (1000 * 60 * 60) : 0;
                    const isVeryStale = filteredPersonal?.data_stale && hoursSinceSync > 2;

                    // Only log when there are actual issues
                    // if (hasIssues) {
                    //   console.log('[DailyBrief] OAuth/Connection Warning:', {
                    //     gmail_needs_reconnect: gmailNeedsReconnect,
                    //     calendar_needs_reconnect: calendarNeedsReconnect,
                    //     gmail_not_connected: gmailNotConnected,
                    //     calendar_not_connected: calendarNotConnected,
                    //     data_stale: filteredPersonal?.data_stale,
                    //     hours_since_sync: hoursSinceSync.toFixed(1),
                    //     is_very_stale: isVeryStale,
                    //   });
                    // }

                    return null;
                  })()}

                  {/* Show warning if integrations need reconnection OR are not connected */}
                  {(() => {
                    const gmailNeedsReconnect = filteredPersonal?.integrations?.gmail?.needs_reconnect === true;
                    const calendarNeedsReconnect = filteredPersonal?.integrations?.calendar?.needs_reconnect === true;
                    const gmailNotConnected = filteredPersonal?.integrations?.gmail?.connected === false;
                    const calendarNotConnected = filteredPersonal?.integrations?.calendar?.connected === false;

                    // Check if data is stale AND very old (more than 2 hours)
                    const lastSyncDate = filteredPersonal?.last_sync ? new Date(filteredPersonal.last_sync) : null;
                    const hoursSinceSync = lastSyncDate ? (Date.now() - lastSyncDate.getTime()) / (1000 * 60 * 60) : 0;
                    const isVeryStale = filteredPersonal?.data_stale && hoursSinceSync > 2;

                    const gmailHasIssue = gmailNeedsReconnect || gmailNotConnected;
                    const calendarHasIssue = calendarNeedsReconnect || calendarNotConnected;

                    const showWarning =
                      filteredPersonal?.needs_reconnect ||
                      gmailHasIssue ||
                      calendarHasIssue ||
                      isVeryStale;

                    if (!showWarning) return null;

                    // Determine the message
                    const affectedServices = [];
                    if (gmailHasIssue) affectedServices.push('Gmail');
                    if (calendarHasIssue) affectedServices.push('Calendar');

                    const isExpired = gmailNeedsReconnect || calendarNeedsReconnect;
                    const isNotConnected = gmailNotConnected || calendarNotConnected;

                    let message = '';

                    // If only showing because data is very stale (fallback detection)
                    if (isVeryStale && !gmailHasIssue && !calendarHasIssue && !filteredPersonal?.needs_reconnect) {
                      message = 'Your data hasn\'t updated in over 2 hours. This usually means your Gmail or Calendar connection has expired. ';
                    } else {
                      message = 'Your ';
                      if (affectedServices.length === 2) {
                        message += affectedServices.join(' and ');
                      } else if (affectedServices.length === 1) {
                        message += affectedServices[0];
                      } else {
                        message += 'integrations';
                      }

                      if (isExpired && isNotConnected) {
                        message += ' connections need attention. ';
                      } else if (isExpired) {
                        message += affectedServices.length > 1 ? ' connections expired. ' : ' connection expired. ';
                      } else if (isNotConnected) {
                        message += affectedServices.length > 1 ? ' are not connected. ' : ' is not connected. ';
                      } else {
                        message += ' need attention. ';
                      }
                    }

                    return (
                      <div className="integration-warning">
                        <div className="warning-icon">⚠️</div>
                        <div className="warning-content">
                          <h4>Connection Issue</h4>
                          <p>
                            {message}
                            <Link to="/settings">
                              {isNotConnected && !isExpired ? 'Connect' : 'Reconnect'} in Settings
                            </Link> to get fresh updates.
                          </p>
                        </div>
                      </div>
                    );
                  })()}

                  <div className={`canon-section ${filteredPersonal?.data_stale ? "stale-data" : ""}`}>
                    <div className="timeline-hero-header">
                      <h2 className="timeline-hero-title">Timeline</h2>
                      {filteredPersonal?.last_sync && (
                        <div className="last-sync-indicator">
                          Last updated: {formatRelativeTime(filteredPersonal.last_sync)}
                          {filteredPersonal.data_stale && " (Data may be outdated)"}
                        </div>
                      )}
                    </div>
                    {hiddenCount > 0 && (
                      <div
                        className="hidden-tasks-notice"
                        style={{
                          padding: "8px 16px",
                          background: "#f0f0f0",
                          borderRadius: "4px",
                          margin: "8px 0",
                          fontSize: "14px",
                          color: "#666",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          gap: 12,
                        }}
                      >
                        <span>
                          {hiddenCount} task{hiddenCount !== 1 ? "s" : ""} hidden
                        </span>
                        <button
                          onClick={() => setDismissedItems([])}
                          style={{
                            padding: "4px 12px",
                            background: "#007bff",
                            color: "white",
                            border: "none",
                            borderRadius: "4px",
                            cursor: "pointer",
                          }}
                        >
                          Show all
                        </button>
                      </div>
                    )}
                    <div className="canon-content">
                      <Timeline
                        items={heroTimeline}
                        onComplete={handleComplete}
                        onDelete={handleDelete}
                        onRefresh={handleTimelineRefresh}
                      />
                    </div>
                  </div>
            </div>
          </>
        )}
      </div>
      {showDebug && (
        <DebugContextModal
          context={debugContext}
          onClose={() => setShowDebug(false)}
        />
      )}
      <CompletedSidebar
        items={completedItems}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen((o) => !o)}
        onUndo={handleUndo}
      />
      {!sidebarOpen && completedItems.length > 0 && (
        <button className="completed-toggle" onClick={() => setSidebarOpen(true)}>
          ✓ {completedItems.length} Completed
        </button>
      )}
    </div>
  );
}
