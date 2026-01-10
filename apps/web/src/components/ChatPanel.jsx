import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import "./ChatPanel.css";
import ChatBubble from "./ChatBubble";
import NotificationBanner from "./NotificationBanner";
import { API_BASE_URL } from "../config";
import {
  getUserAgent,
  askInChat,
  listExtensionClients,
  dispatchChat,
  getTaskStatus,
  getUpdatesSinceCursor,
  setCodeEventCursor,
  sendExtensionNotify,
} from "../lib/tasksApi";
import { searchRAG, formatRAGContext } from "../api/ragApi";
import { shouldUseRAG, getRAGTriggerReason } from "../utils/ragTriggers";
import { logger } from "../utils/logger";
import { getUnreadCount } from "../api/notificationApi";
import ContextUsedDrawer from "./ContextUsedDrawer";

export default function ChatPanel({
  user,
  roomId,
  chatId,
  initialMessages = [],
  onMessagesUpdate = null,
}) {
  logger.debug("[ChatPanel] Rendered with:", {
    chatId,
    roomId,
    user: user?.email || user?.name || user?.id,
    hasInitialMessages: (initialMessages?.length || 0) > 0,
  });

  const greeting = useMemo(
    () => ({
      sender: "ai",
      text: `Hey ${user?.name || "there"} — how can I help today?`,
    }),
    [user?.name]
  );
  
  const [messages, setMessages] = useState([]);
  const [contextByMsgId, setContextByMsgId] = useState({});
  const [selectedPreviewMsgId, setSelectedPreviewMsgId] = useState(null);
  const previewToggleKey = "DEBUG_CONTEXT_PREVIEW";
  const defaultPreviewEnabled =
    (import.meta.env?.DEV && localStorage.getItem(previewToggleKey) !== "0") ||
    localStorage.getItem(previewToggleKey) === "1";
  const [previewEnabled, setPreviewEnabled] = useState(defaultPreviewEnabled);
  const [sendError, setSendError] = useState(null);
  const diagToggleKey = "CHAT_DIAGNOSTICS_MODE";
  const [diagnosticsMode, setDiagnosticsMode] = useState(
    localStorage.getItem(diagToggleKey) === "1"
  );
  const [lastDiagnostics, setLastDiagnostics] = useState(null);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("");
  const [roomError, setRoomError] = useState("");
  const [_agentId, setAgentId] = useState(null);
  const [teamUpdatesCount, setTeamUpdatesCount] = useState(0);
  const [teamSummary, setTeamSummary] = useState(null);
  const [showTeamSummary, setShowTeamSummary] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [uploadPreviews, setUploadPreviews] = useState([]);
  const [ragInfo, setRagInfo] = useState(null);
  const fileInputRef = useRef(null);
  const ragTimeoutRef = useRef(null);
  const lastChatIdRef = useRef(null);
  const messagesInitialized = useRef(false);
  const sendModeKeyPrefix = "CHAT_SEND_MODE:";
  const [sendMode, setSendMode] = useState("site"); // "site" | "agent" | "patch"
  const [repoOptions, setRepoOptions] = useState([]);
  const [selectedRepoId, setSelectedRepoId] = useState(null);
  const [extensionBanner, setExtensionBanner] = useState("");
  const [conflictHint, setConflictHint] = useState(null);
  const [codeUpdates, setCodeUpdates] = useState([]);
  const [codeUpdatesVisible, setCodeUpdatesVisible] = useState(false);
  const [codeUpdatesLoading, setCodeUpdatesLoading] = useState(false);
  const [codeUpdatesError, setCodeUpdatesError] = useState("");
  const [newUpdatesCount, setNewUpdatesCount] = useState(0);
  const [expandedResults, setExpandedResults] = useState({});
  const [lastUpdateFilters, setLastUpdateFilters] = useState(null);
  const [autoSurfaceUpdates, setAutoSurfaceUpdates] = useState(
    localStorage.getItem("CHAT_AUTO_UPDATES") === "1"
  );
  const [patchDiff, setPatchDiff] = useState("");
  const [patchBaseSha, setPatchBaseSha] = useState("");
  const [patchFiles, setPatchFiles] = useState("");
  const [patchError, setPatchError] = useState("");
  const [smokeResult, setSmokeResult] = useState(null);
  const [smokeRunning, setSmokeRunning] = useState(false);
  const conflictHintTimeoutRef = useRef(null);
  const pollIntervalsRef = useRef({});

  useEffect(() => {
    logger.debug("[DEBUG] chatId:", chatId);
    logger.debug("[DEBUG] roomId:", roomId);
    logger.debug("[DEBUG] user:", user);
    logger.debug("[DEBUG] input disabled?", !chatId && !roomId);
  }, [chatId, roomId, user]);

  useEffect(() => {
    const key = `${sendModeKeyPrefix}${chatId || "default"}`;
    const stored = localStorage.getItem(key);
    if (stored === "patch") {
      setSendMode("patch");
    } else if (stored === "vscode" || stored === "agent") {
      setSendMode("agent");
    } else {
      setSendMode("site");
    }
  }, [chatId]);

  useEffect(() => {
    let cancelled = false;
    if (sendMode === "site" || repoOptions.length > 0) return;

    (async () => {
      try {
        const clients = await listExtensionClients();
        if (cancelled) return;
        const items = Array.isArray(clients) ? clients : clients?.items || [];
        setRepoOptions(items);
      } catch (err) {
        logger.warn("[ChatPanel] Failed to prefetch extension clients", err);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [sendMode, repoOptions.length]);

  useEffect(() => {
    logger.debug("[ChatPanel] messages:", messages);
  }, [messages]);

  useEffect(() => {
    if (!import.meta.env?.DEV) return;
    (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/health`, { credentials: "include" });
        console.info("[ChatPanel] API health check", res.status);
      } catch (err) {
        console.warn("[ChatPanel] API health check failed", err);
      }
    })();
  }, []);

  useEffect(() => {
    logger.debug("[ChatPanel] input:", input);
  }, [input]);

  useEffect(() => {
    return () => {
      if (ragTimeoutRef.current) {
        clearTimeout(ragTimeoutRef.current);
      }
      if (conflictHintTimeoutRef.current) {
        clearTimeout(conflictHintTimeoutRef.current);
      }
      Object.values(pollIntervalsRef.current || {}).forEach((id) => {
        if (id) clearInterval(id);
      });
    };
  }, []);

  const scheduleClearRagInfo = useCallback(() => {
    if (ragTimeoutRef.current) {
      clearTimeout(ragTimeoutRef.current);
    }
    ragTimeoutRef.current = setTimeout(() => setRagInfo(null), 3000);
  }, []);

  const formatRelativeTime = (timestamp) => {
    if (!timestamp) return "recently";
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return "recently";
    const diffMs = Date.now() - date.getTime();
    const diffSec = Math.max(0, Math.floor(diffMs / 1000));
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 48) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}d ago`;
  };

  const getActiveRepoId = useCallback(() => {
    const first = repoOptions?.[0];
    return selectedRepoId || first?.id || first?.repo_id || null;
  }, [selectedRepoId, repoOptions]);

  const extractFocusFilters = useCallback(() => {
    const latestUserMsg = [...messages]
      .reverse()
      .find((m) => m.role === "user" || m.sender === "user");
    const text = (latestUserMsg?.text || latestUserMsg?.content || "").toLowerCase();

    const systems = new Set();
    const impacts = new Set();
    const files = new Set();

    const addIfIncludes = (keywords, targetSet) => {
      keywords.forEach((kw) => {
        if (text.includes(kw)) {
          targetSet.add(kw.group || kw.label || kw);
        }
      });
    };

    addIfIncludes(
      [
        { label: "auth", group: "auth" },
        { label: "login", group: "auth" },
        { label: "token", group: "auth" },
        { label: "jwt", group: "auth" },
        { label: "oauth", group: "auth" },
      ],
      systems
    );
    addIfIncludes(
      [
        { label: "api", group: "api" },
        { label: "endpoint", group: "api" },
        { label: "contract", group: "api" },
        { label: "schema", group: "api" },
      ],
      systems
    );
    addIfIncludes(
      [
        { label: "db", group: "database" },
        { label: "database", group: "database" },
        { label: "postgres", group: "database" },
        { label: "schema", group: "database" },
        { label: "migration", group: "database" },
      ],
      systems
    );
    addIfIncludes(
      [
        { label: "ui", group: "frontend" },
        { label: "frontend", group: "frontend" },
        { label: "react", group: "frontend" },
        { label: "component", group: "frontend" },
      ],
      systems
    );
    addIfIncludes(
      [
        { label: "config", group: "config" },
        { label: "env", group: "config" },
        { label: "yaml", group: "config" },
      ],
      systems
    );
    addIfIncludes(
      [
        { label: "billing", group: "billing" },
        { label: "payment", group: "billing" },
        { label: "stripe", group: "billing" },
      ],
      systems
    );

    addIfIncludes(
      [
        { label: "schema", group: "db_schema" },
        { label: "migration", group: "db_schema" },
      ],
      impacts
    );
    addIfIncludes(
      [
        { label: "contract", group: "api_contract" },
        { label: "endpoint", group: "api_contract" },
      ],
      impacts
    );
    addIfIncludes(
      [
        { label: "auth", group: "auth_flow" },
        { label: "login", group: "auth_flow" },
        { label: "token", group: "auth_flow" },
      ],
      impacts
    );
    addIfIncludes([{ label: "config", group: "config" }], impacts);
    addIfIncludes([{ label: "dependency", group: "deps" }, { label: "package", group: "deps" }], impacts);

    const fileRegex = /\b(?:src|app|packages|services|api|frontend)\/[\w./-]+\b/g;
    const fileMatches = text.match(fileRegex);
    if (fileMatches) {
      fileMatches.forEach((f) => files.add(f));
    }

    return {
      focus_systems: Array.from(systems),
      focus_impacts: Array.from(impacts),
      focus_files: Array.from(files),
    };
  }, [messages]);

  const setMessagesAndNotify = useCallback(
    (updater, notify = true) => {
      setMessages((prev) => {
        const nextValue = typeof updater === "function" ? updater(prev) : updater;
        const next = nextValue ?? [];
        if (notify && typeof onMessagesUpdate === "function") {
          if (onMessagesUpdate.length >= 2) {
            onMessagesUpdate(chatId, next);
          } else {
            onMessagesUpdate(next);
          }
        }
        return next;
      });
    },
    [chatId, onMessagesUpdate]
  );

  const pollTaskStatus = useCallback(
    (taskId, messageId, repoIdHint = null) => {
      let pollCount = 0;
      const maxPolls = 30; // 60 seconds at 2s intervals

      const pollInterval = setInterval(async () => {
        pollCount++;

        try {
          const taskData = await getTaskStatus(taskId);
          const taskStatus = taskData?.status || "unknown";
          if (!repoIdHint && taskData?.repo_id) {
            repoIdHint = taskData.repo_id;
          }
          const isTerminal = ["done", "error", "failed", "cancelled"].includes(taskStatus);

          // Update the message in place
          setMessagesAndNotify(
            (prev) =>
              prev.map((msg) => {
                if (msg.id !== messageId) return msg;

                let statusText = `Sent to VS Code agent — status: ${taskStatus}`;

                if (isTerminal) {
                  if (taskStatus === "done" && taskData?.result) {
                    statusText = `✓ Task completed`;
                  } else if (taskStatus === "error" || taskStatus === "failed") {
                    const errorMsg = taskData?.error || taskData?.result || "Task failed";
                    statusText = `✗ Task failed: ${errorMsg}`;
                  } else if (taskStatus === "cancelled") {
                    statusText = `⊘ Task cancelled`;
                  }
                }

                return {
                  ...msg,
                  text: statusText,
                  vscodeTask: {
                    ...msg.vscodeTask,
                    status: taskStatus,
                    result: taskData?.result,
                    error: taskData?.error,
                    error_code: taskData?.error_code,
                    updated_at: new Date().toISOString(),
                  },
                };
              }),
            false
          );

          // Stop polling if terminal or max attempts reached
          if (isTerminal || pollCount >= maxPolls) {
            clearInterval(pollInterval);
            delete pollIntervalsRef.current[messageId];

            if (isTerminal && (diagnosticsMode || autoSurfaceUpdates)) {
              const repoId =
                repoIdHint ||
                getActiveRepoId();
              if (repoId) {
                try {
                  const focus = extractFocusFilters();
                  const { events } = await getUpdatesSinceCursor(repoId, {
                    limit: 5,
                    focus_systems: focus.focus_systems,
                    focus_impacts: focus.focus_impacts,
                    focus_files: focus.focus_files,
                  });
                  if (Array.isArray(events) && events.length > 0) {
                    setNewUpdatesCount(events.length);
                    const topEvents = events.slice(0, 3);

                    // Notify extension (deduped) without blocking UI
                    try {
                      const newestId = topEvents[0]?.id || topEvents[0]?.event_id;
                      const cursorKey = repoId
                        ? `EXT_NOTIFY_CURSOR:${repoId}`
                        : "EXT_NOTIFY_CURSOR:default";
                      const lastCursor = localStorage.getItem(cursorKey);
                      if (newestId && lastCursor !== newestId) {
                        const summaryImpacts = (focus.focus_impacts || []).join(", ");
                        const { ok, error_code } = await sendExtensionNotify(
                          {
                            severity: "info",
                            title: "Heads up: recent changes",
                            message: `${topEvents.length} relevant updates since you last checked${
                              summaryImpacts ? ` (${summaryImpacts})` : ""
                            }. Open ParallelOS for details.`,
                            events: topEvents.map((ev) => ({
                              id: ev.id || ev.event_id,
                              summary: ev.summary || ev.title,
                              user_name: ev.user_name,
                              user_id: ev.user_id,
                              impact_tags: ev.impact_tags,
                              systems_touched: ev.systems_touched,
                              created_at: ev.created_at || ev.timestamp,
                            })),
                            source: "web_autosurface",
                            chat_id: chatId || undefined,
                          },
                          repoId
                        );
                        if (ok) {
                          localStorage.setItem(cursorKey, newestId);
                        } else if (diagnosticsMode) {
                          console.info("[ExtensionNotify] skipped", { error_code, repoId });
                        }
                      }
                    } catch (err) {
                      if (diagnosticsMode) {
                        console.debug("[ExtensionNotify] failed", err);
                      }
                    }

                    setMessagesAndNotify(
                      (prev) => [
                        ...prev,
                        {
                          id: `updates-${Date.now()}`,
                          sender: "ai",
                          role: "assistant",
                          text: "FYI — relevant updates since you last checked:",
                          updateNote: {
                            events: topEvents,
                            repo_id: repoId,
                            last_seen_event_id:
                              topEvents[0]?.id || topEvents[0]?.event_id,
                          },
                        },
                      ],
                      false
                    );
                  }
                } catch (err) {
                  logger.debug("[CodeEvents] Background updates check skipped", err);
                }
              }
            }
          }
        } catch (err) {
          logger.error("[TaskPoll] Failed to fetch task status:", err);

          // Stop polling on error after a few retries
          if (pollCount >= 5) {
            clearInterval(pollInterval);
            delete pollIntervalsRef.current[messageId];
            setMessagesAndNotify(
              (prev) =>
                prev.map((msg) => {
                  if (msg.id !== messageId) return msg;
                  return {
                    ...msg,
                    text: `⚠️ Lost connection to VS Code agent (task: ${taskId})`,
                  };
                }),
              false
            );
          }
        }
      }, 2000); // Poll every 2 seconds

      pollIntervalsRef.current[messageId] = pollInterval;

      // Cleanup on unmount
      return () => clearInterval(pollInterval);
    },
    [
      setMessagesAndNotify,
      diagnosticsMode,
      getUpdatesSinceCursor,
      getActiveRepoId,
      extractFocusFilters,
      autoSurfaceUpdates,
      chatId,
      sendExtensionNotify,
    ]
  );

  const sendPatch = useCallback(async () => {
    if (sendMode !== "patch") return;
    const diff = patchDiff || "";
    const maxBytes = 200 * 1024; // 200KB guard
    if (new Blob([diff]).size > maxBytes) {
      setPatchError("Patch is too large (over 200KB). Please trim before sending.");
      return;
    }
    if (!diff.trim()) {
      setPatchError("Paste a unified diff before sending.");
      return;
    }
    setPatchError("");
    setStatus("Sending patch to VS Code agent...");
    const targetChatId = chatId || roomId;
    const files = patchFiles
      .split(",")
      .map((f) => f.trim())
      .filter(Boolean);
    try {
      const { data, diagnostics } = await dispatchChat(targetChatId, {
        mode: "vscode",
        content: input?.trim() || "Apply this patch",
        repo_id: selectedRepoId || undefined,
        task_type: "APPLY_PATCH",
        patch: {
          format: "unified_diff",
          diff,
          base_sha: patchBaseSha || undefined,
          files: files.length > 0 ? files : undefined,
        },
      });
      setLastDiagnostics(diagnostics || null);

      if (data?.error_code === "REPO_REQUIRED") {
        const clients = await listExtensionClients().catch(() => []);
        setRepoOptions(Array.isArray(clients) ? clients : clients?.items || []);
        setExtensionBanner("Select a repo to send patch to VS Code agent.");
        setStatus("");
        setSendError("Repo required");
        return;
      }

      if (data?.error_code === "EXTENSION_OFFLINE") {
        setExtensionBanner("VS Code agent offline — open VS Code to connect.");
        setStatus("");
        setSendError("Agent offline");
        return;
      }

      const taskId = data?.task_id || data?.id || "pending";
      const clientMsgId = `vscode-patch-${Date.now()}-${Math.random().toString(16).slice(2)}`;

          setMessagesAndNotify((prev) => [
            ...prev,
            {
              id: clientMsgId,
              sender: "ai",
              text: `Patch sent to VS Code agent — status: pending (task_id=${taskId})`,
              role: "assistant",
              vscodeTask: {
                task_id: taskId,
                status: "pending",
                created_at: new Date().toISOString(),
                task_type: "APPLY_PATCH",
                repo_id: selectedRepoId || undefined,
              },
            },
          ]);

      setStatus("");
      setSendError(null);
      setPatchDiff("");
      setPatchBaseSha("");
      setPatchFiles("");

      if (taskId && taskId !== "pending") {
        pollTaskStatus(taskId, clientMsgId, selectedRepoId || undefined);
      }
    } catch (err) {
      setLastDiagnostics(err?.diagnostics || null);
      setStatus(`Error: ${err?.message || "Request failed"}`);
      setSendError(err?.message || "Request failed");
    }
  }, [
    sendMode,
    patchDiff,
    patchBaseSha,
    patchFiles,
    chatId,
    roomId,
    selectedRepoId,
    input,
    dispatchChat,
    listExtensionClients,
    setMessagesAndNotify,
    pollTaskStatus,
  ]);

  const runSmokeTest = useCallback(async () => {
    const repoId = getActiveRepoId();
    setSmokeRunning(true);
    setSmokeResult(null);

    const makeReqId = () => `web-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
    const logResult = (label, res, reqId) => {
      const serverReqId = res.headers.get("X-Request-Id");
      console.info("[SmokeTest]", {
        step: label,
        status: res.status,
        ok: res.ok,
        client_request_id: reqId,
        server_request_id: serverReqId,
      });
      return serverReqId;
    };

    try {
      // 1) cursor
      const cursorReqId = makeReqId();
      const cursorUrl = new URL(`${API_BASE_URL}/api/v1/code-events/cursor`);
      if (repoId) cursorUrl.searchParams.set("repo_id", repoId);
      const cursorRes = await fetch(cursorUrl.toString(), {
        method: "GET",
        credentials: "include",
        headers: { "X-Client-Request-Id": cursorReqId },
      });
      logResult("cursor", cursorRes, cursorReqId);
      if (!cursorRes.ok) throw new Error("cursor");

      // 2) updates-since-cursor
      const updatesReqId = makeReqId();
      const updatesUrl = new URL(`${API_BASE_URL}/api/v1/code-events/updates-since-cursor`);
      if (repoId) updatesUrl.searchParams.set("repo_id", repoId);
      updatesUrl.searchParams.set("limit", "1");
      const updatesRes = await fetch(updatesUrl.toString(), {
        method: "GET",
        credentials: "include",
        headers: { "X-Client-Request-Id": updatesReqId },
      });
      logResult("updates-since-cursor", updatesRes, updatesReqId);
      if (!updatesRes.ok) throw new Error("updates-since-cursor");

      // 3) extension clients if agent/patch mode
      if (sendMode !== "site") {
        const clientsReqId = makeReqId();
        const clientsRes = await fetch(`${API_BASE_URL}/api/v1/extension/clients`, {
          credentials: "include",
          headers: { "X-Client-Request-Id": clientsReqId },
        });
        logResult("extension-clients", clientsRes, clientsReqId);
        if (!clientsRes.ok) throw new Error("extension-clients");
      }

      setSmokeResult({ ok: true, message: "Smoke test OK" });
    } catch (err) {
      setSmokeResult({ ok: false, message: `Smoke test failed: ${err.message || "unknown"}` });
    } finally {
      setSmokeRunning(false);
    }
  }, [getActiveRepoId, sendMode]);

  const handleCheckUpdates = useCallback(async () => {
    if (sendMode === "site") return;
    const repoId = getActiveRepoId();
    if (!repoId) {
      setCodeUpdatesError("Select a repo to check code updates.");
      setCodeUpdatesVisible(true);
      return;
    }

    setCodeUpdatesLoading(true);
    setCodeUpdatesError("");
    try {
      const focus = extractFocusFilters();
      setLastUpdateFilters(focus);
      const { events } = await getUpdatesSinceCursor(repoId, {
        limit: 10,
        focus_systems: focus.focus_systems,
        focus_impacts: focus.focus_impacts,
        focus_files: focus.focus_files,
      });
      setCodeUpdates(Array.isArray(events) ? events.slice(0, 10) : []);
      setCodeUpdatesVisible(true);
      setNewUpdatesCount(0);
    } catch (err) {
      logger.error("[CodeEvents] Failed to fetch updates", err);
      setCodeUpdatesError("Failed to fetch updates. Check console.");
      setCodeUpdatesVisible(true);
    } finally {
      setCodeUpdatesLoading(false);
    }
  }, [sendMode, selectedRepoId, repoOptions, getActiveRepoId, extractFocusFilters]);

  const handleMarkUpdatesSeen = useCallback(async () => {
    const repoId = getActiveRepoId();
    if (!repoId) return;
    const latest = codeUpdates?.[0];
    const last_seen_event_id = latest?.id || latest?.event_id;
    const last_seen_at =
      latest?.created_at || latest?.timestamp || new Date().toISOString();

    try {
      await setCodeEventCursor({
        repo_id: repoId,
        last_seen_event_id,
        last_seen_at,
      });
    } catch (err) {
      logger.warn("[CodeEvents] Failed to set cursor", err);
    } finally {
      setCodeUpdatesVisible(false);
      setCodeUpdates([]);
      setNewUpdatesCount(0);
    }
  }, [codeUpdates, selectedRepoId, repoOptions, getActiveRepoId]);

  // TEMPORARILY DISABLED FOR DEBUGGING:
  // useEffect(() => {
  //   const timer = setTimeout(() => {
  //     if (!chatId && !roomId) {
  //       console.error("[ChatPanel] Chat not loaded after 2s. State:", {
  //         chatId,
  //         roomId,
  //         user,
  //       });
  //       setStatus("Failed to load chat. Please refresh the page.");
  //     }
  //   }, 2000);
  //
  //   return () => clearTimeout(timer);
  // }, [chatId, roomId, user]);

  // Fetch user's agent ID on mount
  useEffect(() => {
    if (!user?.id) return;
    
    let cancelled = false;
    const loadAgent = async () => {
      try {
        const data = await getUserAgent(user.id);
        if (cancelled) return;
        
        const nextAgentId = data?.agent_id || data?.id;
        setAgentId(nextAgentId);
      } catch (err) {
        if (!cancelled) {
          logger.error("[ChatPanel] Failed to load agent", err);
        }
      }
    };

    loadAgent();
    return () => {
      cancelled = true;
    };
  }, [user?.id]);

  // Poll unread counts for team updates
  useEffect(() => {
    let cancelled = false;
    const fetchUnread = async () => {
      try {
        const count = await getUnreadCount();
        if (cancelled) return;
        setTeamUpdatesCount(count);
      } catch {
        // silently fail
      }
    };
    fetchUnread();
    const interval = setInterval(fetchUnread, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const handleViewTeamUpdates = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/notifications/team-updates/summary`, {
        credentials: "include",
      });
      if (!res.ok) return;
      const data = await res.json();
      setTeamSummary(data || {});
      setShowTeamSummary(true);
      setTeamUpdatesCount(0);
    } catch (err) {
      logger.error("Failed to load team updates summary", err);
    }
  };

  const handleNotificationSummary = async (notificationData) => {
    // Build a summary prompt for the LLM
    const notifications = notificationData.notifications || [];
    const { total, urgentCount, byType } = notificationData;

    // Create a structured summary for the LLM
    const summaryLines = [
      `You have ${total} notification${total !== 1 ? 's' : ''}${urgentCount > 0 ? `, including ${urgentCount} urgent` : ''}.`,
      "",
    ];

    // Group by type
    Object.entries(byType).forEach(([type, notifs]) => {
      summaryLines.push(`**${type}** (${notifs.length}):`);
      notifs.slice(0, 3).forEach(n => {
        summaryLines.push(`- ${n.title || n.message || 'Notification'}`);
      });
      if (notifs.length > 3) {
        summaryLines.push(`  ...and ${notifs.length - 3} more`);
      }
      summaryLines.push("");
    });

    summaryLines.push("Would you like me to explain any of these in detail?");

    // Send as an AI message in the chat
    const aiMessage = {
      sender: "ai",
      text: summaryLines.join("\n"),
      role: "assistant",
    };

    setMessagesAndNotify((prev) => [...prev, aiMessage]);
  };

  // OPTIMIZED: Handle messages when chat/initialMessages change
  // KEY FIX: Only clear messages when actually switching chats, not on every render
  useEffect(() => {
    const chatChanged = lastChatIdRef.current !== chatId;
    
    if (chatChanged) {
      lastChatIdRef.current = chatId;
      messagesInitialized.current = false;
    }

    // No chat selected - show greeting
    if (!chatId) {
      setMessagesAndNotify([greeting], false);
      messagesInitialized.current = true;
      return;
    }

    // Have messages to display
    if (Array.isArray(initialMessages) && initialMessages.length > 0) {
      // Simple mapping - no complex filtering to avoid race conditions
      const mapped = initialMessages.map((m) => ({
        sender: m.role === "user" ? "user" : "ai",
        text: m.content || m.text || "",
        role: m.role,
      }));

      setMessagesAndNotify(mapped, false);
      messagesInitialized.current = true;
    } else if (chatChanged && !messagesInitialized.current) {
      // Only clear on actual chat switch, not on re-renders
      setMessagesAndNotify([], false);
      messagesInitialized.current = true;
    }
  }, [chatId, initialMessages, greeting, setMessagesAndNotify]);

  // SSE event listener for status updates
  const formatStatus = useMemo(
    () => ({
      ask_received: ({ meta }) => `Ask received (${meta?.mode || "team"})`,
      routing_agent: ({ meta }) => `Routing to ${meta?.agent || "agent"}`,
      agent_reply: ({ meta }) => `Reply from ${meta?.agent || "agent"}`,
      team_fanout_start: () => "Querying teammates...",
      synthesizing: () => "Synthesizing responses...",
      synthesis_complete: () => "Synthesis complete",
    }),
    []
  );

  useEffect(() => {
    if ((!roomId && !chatId) || !user?.id) return;

    const params = new URLSearchParams();
    if (chatId) params.set("chat_id", chatId);
    if (roomId) params.set("room_id", roomId);
    params.set("user_id", user.id);

    const url = `${API_BASE_URL}/api/events?${params.toString()}`;
    const source = new EventSource(url);

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "status") {
          const formatter = formatStatus[data.step];
          const text = formatter ? formatter(data) : data.step;
          setStatus(text);
        } else if (data.type === "error") {
          setStatus(`Error: ${data.message}`);
        }
      } catch (err) {
        logger.error("Error parsing event", err);
      }
    };

    source.onerror = () => {
      setStatus("Disconnected from backend");
    };

    return () => source.close();
  }, [formatStatus, roomId, chatId, user?.id]);

  // Guard: Don't render until user is loaded
  if (!user) {
    return (
      <div className="chat-wrapper">
        <div className="chat-scroll">
          <div className="status-bubble">Loading your workspace…</div>
        </div>
      </div>
    );
  }

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;

    setSelectedFiles(files);

    const previews = [];
    files.forEach((file) => {
      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = (event) => {
          previews.push({
            type: "image",
            url: event.target?.result,
            name: file.name,
          });
          setUploadPreviews([...previews]);
        };
        reader.readAsDataURL(file);
      } else {
        previews.push({
          type: "file",
          name: file.name,
          size: `${(file.size / 1024).toFixed(1)} KB`,
        });
        setUploadPreviews([...previews]);
      }
    });
  };

  const removeFile = (index) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
    setUploadPreviews((prev) => prev.filter((_, i) => i !== index));
  };

  async function send() {
    if (!input.trim() && selectedFiles.length === 0) return;

    if (!chatId && !roomId) {
      setRoomError("No chat is available yet. Try again in a moment.");
      setStatus("Waiting for chat to be ready…");
      return;
    }

    const userMessage = {
      sender: "user",
      text:
        input ||
        (selectedFiles.length > 0
          ? `[Uploaded ${selectedFiles.length} file(s)]`
          : ""),
      role: "user",
      user_id: user.id,
      sender_id: `user:${user.id}`,
    };
    
    setMessagesAndNotify((prev) => [...prev, userMessage]);
    const currentInput = input;
    const currentFiles = selectedFiles;
    const trimmedInput = currentInput.trim();
    setInput("");
    setSelectedFiles([]);
    setUploadPreviews([]);

    try {
      let ragContext = null;
      let usedRAG = false;

      if (trimmedInput && shouldUseRAG(trimmedInput)) {
        if (roomId) {
          const reason = getRAGTriggerReason(trimmedInput);
          usedRAG = true;
          setRagInfo({ status: "searching", reason });

          try {
            const ragResults = await searchRAG(roomId, trimmedInput, 10);
            const results =
              ragResults?.results ||
              ragResults?.items ||
              ragResults?.matches ||
              [];

            if (results.length > 0) {
              ragContext = formatRAGContext(results);
              setRagInfo({
                status: "found",
                count: results.length,
                reason,
              });
            } else {
              setRagInfo({ status: "none", reason });
            }
          } catch (err) {
            logger.error("[Chat] RAG search failed:", err);
            setRagInfo({ status: "none", reason: "History search failed" });
          } finally {
            scheduleClearRagInfo();
          }
        } else {
          logger.debug("[Chat] RAG skipped: no roomId available");
        }
      } else {
        setRagInfo(null);
      }

      const messageContent = ragContext
        ? `${ragContext}\n\n<user_query>\n${currentInput}\n</user_query>`
        : currentInput;

      const isAgentMode = sendMode === "agent";
      setStatus(isAgentMode ? "Sending to VS Code agent..." : "Sending to backend...");
      const targetChatId = chatId || roomId;
      if (isAgentMode) {
        // Use dispatchChat instead of sendExtensionTask
        try {
          const { data, diagnostics } = await dispatchChat(targetChatId, {
            mode: "vscode",
            content: trimmedInput,
            repo_id: selectedRepoId || undefined,
          });
          setLastDiagnostics(diagnostics || null);

          if (data?.error_code === "REPO_REQUIRED") {
            const clients = await listExtensionClients().catch(() => []);
            setRepoOptions(Array.isArray(clients) ? clients : clients?.items || []);
            setExtensionBanner("Select a repo to send task to VS Code agent.");
            setStatus("");
            setSendError("Repo required");
            return;
          }

          if (data?.error_code === "EXTENSION_OFFLINE") {
            setExtensionBanner("VS Code agent offline — open VS Code to connect.");
            setStatus("");
            setSendError("Agent offline");
            return;
          }

          const taskId = data?.task_id || data?.id || "pending";
          const clientMsgId = `vscode-task-${Date.now()}-${Math.random().toString(16).slice(2)}`;

          // Check for conflict hint from backend
          if (data?.conflict_hint && data.conflict_hint.count > 0) {
            const hint = data.conflict_hint;
            const topEvent = hint.top?.[0];
            const systems = hint.systems?.join(", ") || "code";
            const user = topEvent?.user_name || topEvent?.user_id || "a teammate";

            // Calculate time ago
            let timeAgo = "recently";
            if (topEvent?.created_at) {
              const now = new Date();
              const eventTime = new Date(topEvent.created_at);
              const diffMs = now - eventTime;
              const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
              const diffDays = Math.floor(diffHours / 24);

              if (diffDays > 0) {
                timeAgo = `${diffDays}d ago`;
              } else if (diffHours > 0) {
                timeAgo = `${diffHours}h ago`;
              } else {
                timeAgo = "recently";
              }
            }

            setConflictHint({
              message: `Heads up: recent activity in ${systems} by ${user} (${timeAgo})`,
              count: hint.count,
              systems: hint.systems,
            });

            // Auto-dismiss after 10 seconds
            if (conflictHintTimeoutRef.current) {
              clearTimeout(conflictHintTimeoutRef.current);
            }
            conflictHintTimeoutRef.current = setTimeout(() => {
              setConflictHint(null);
            }, 10000);
          }

          // Add assistant bubble with task status
          setMessagesAndNotify((prev) => [
            ...prev,
            {
              id: clientMsgId,
              sender: "ai",
              text: `Sent to VS Code agent — status: pending`,
              role: "assistant",
              vscodeTask: {
                task_id: taskId,
                status: "pending",
                created_at: new Date().toISOString(),
                repo_id: selectedRepoId || undefined,
              },
            },
          ]);

          setStatus("");
          setSendError(null);

          // Start polling task status
          if (taskId && taskId !== "pending") {
            pollTaskStatus(taskId, clientMsgId, selectedRepoId || undefined);
          }
        } catch (err) {
          setLastDiagnostics(err?.diagnostics || null);
          setStatus(`Error: ${err?.message || "Request failed"}`);
          setSendError(err?.message || "Request failed");
        }
      } else {
        const payload = {
          user_id: user.id,
          user_name: user.name,
          content: messageContent,
          chat_id: chatId || undefined,
          room_id: roomId || undefined,
          mode: "team",
          fast_path_hint:
            trimmedInput.length <= 120 && !/file|agent|task/i.test(trimmedInput),
        };

        // Note: file uploads are not supported in askInChat; keep existing logic if needed later
        if (currentFiles.length > 0) {
          logger.error("[ChatSend] File uploads not supported in askInChat path");
          throw new Error("File uploads not supported in ask");
        }

        const { data, diagnostics } = await askInChat(targetChatId, payload, {
          includeContextPreview: previewEnabled,
        });
        setLastDiagnostics(diagnostics || null);

        // Backend returns full conversation including user message + assistant response
        // We've already added user message optimistically, so just add assistant response
        const responseMessages = Array.isArray(data)
          ? data
          : Array.isArray(data?.messages)
          ? data.messages
          : [];
        const serverMessages = responseMessages.filter(
          (m) => m.role === "assistant"
        );
        
        if (serverMessages.length > 0) {
          const lastAssistant = serverMessages[serverMessages.length - 1];
          const clientMsgId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
          const assistantMsg = { 
            sender: "ai", 
            text: lastAssistant.content, 
            role: "assistant",
            id: clientMsgId,
            metadata: usedRAG ? { usedRAG: true } : undefined,
          };
          
          // notify=true updates Dashboard so it doesn't need to refetch
          setMessagesAndNotify((prev) => [...prev, assistantMsg], true);
          if (data?.context_preview) {
            setContextByMsgId((prev) => ({
              ...prev,
              [clientMsgId]: data.context_preview,
            }));
            setSelectedPreviewMsgId(clientMsgId);
          }
        } else {
          // Fallback if no assistant message
          setMessagesAndNotify((prev) => [
            ...prev,
            { sender: "ai", text: "Okay, noted.", role: "assistant" },
          ], true);
        }
        
        setStatus("");
        setSendError(null);
      }
    } catch (err) {
      setStatus(`Error: ${err?.message || "Request failed"}`);
      const diag = err?.diagnostics;
      setLastDiagnostics(diag || null);
      const bannerMsg = diag?.classification || err?.message || "Request failed";
      setSendError(
        diag?.client_request_id
          ? `${bannerMsg} (req=${diag.client_request_id})`
          : bannerMsg
      );
      setMessagesAndNotify((prev) => [
        ...prev,
        { sender: "ai", text: "Something went wrong. Try again." },
      ], true);
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault();
    if (sendMode === "patch") {
      sendPatch();
      return;
    }
    send();
  };

  return (
    <div className="chat-wrapper">
      <div className="chat-scroll">
        {messages.map((m, i) => {
          const key = m.id || i;
          if (m.updateNote && m.updateNote.events) {
            const events = m.updateNote.events;
            const top = events[0] || {};
            const handleMarkSeen = async () => {
              const repoId = m.updateNote.repo_id;
              if (!repoId) return;
              const lastId = m.updateNote.last_seen_event_id || top.id || top.event_id;
              try {
                await setCodeEventCursor({
                  repo_id: repoId,
                  last_seen_event_id: lastId,
                  last_seen_at: top.created_at || top.timestamp || new Date().toISOString(),
                });
                setNewUpdatesCount(0);
              } catch (err) {
                logger.warn("[CodeEvents] Mark seen failed", err);
              }
            };
            return (
              <div
                key={key}
                className="chat-bubble ai"
                style={{ borderLeft: "4px solid #0f766e", background: "#ecfeff" }}
              >
                <div className="bubble-content">
                  <div style={{ fontWeight: 600 }}>FYI — relevant updates since you last checked:</div>
                  <ul style={{ margin: "8px 0", paddingLeft: 16 }}>
                    {events.slice(0, 3).map((ev, idx2) => (
                      <li key={ev.id || ev.event_id || idx2} style={{ marginBottom: 4 }}>
                        <div style={{ fontWeight: 500 }}>
                          {ev.summary || ev.title || "Update"}
                        </div>
                        <div style={{ fontSize: 12, color: "#0f172a" }}>
                          {(ev.impact_tags || []).slice(0, 3).join(", ")}
                          {(ev.impact_tags || []).length > 0 ? " · " : ""}
                          {ev.user_name || ev.user_id || "someone"} ·{" "}
                          {formatRelativeTime(ev.created_at || ev.timestamp)}
                        </div>
                      </li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    onClick={handleMarkSeen}
                    style={{
                      border: "1px solid #99f6e4",
                      background: "#ccfbf1",
                      padding: "6px 10px",
                      borderRadius: 8,
                      fontSize: 12,
                      cursor: "pointer",
                    }}
                  >
                    Mark seen
                  </button>
                </div>
              </div>
            );
          }
          if (m.vscodeTask) {
            const task = m.vscodeTask;
            const patchResult =
              task.task_type === "APPLY_PATCH" && task.result && typeof task.result === "object"
                ? task.result
                : null;
            const resultPreview =
              typeof task.result === "string"
                ? task.result
                : task.result
                ? JSON.stringify(task.result, null, 2)
                : "";
            const isTerminal = ["done", "error", "failed", "cancelled"].includes(
              task.status
            );
            const isError =
              task.status === "error" || task.status === "failed";
            return (
              <div
                key={key}
                className="chat-bubble ai"
                style={{ borderLeft: "4px solid #4338ca", background: "#f8fafc" }}
              >
                <div className="bubble-content">
                  <div style={{ fontWeight: 600 }}>
                    {m.text || "VS Code task status"}
                  </div>
                  <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>
                    task_id: {task.task_id || "pending"} · status:{" "}
                    {task.status || "unknown"}
                    {task.updated_at && ` · ${formatRelativeTime(task.updated_at)}`}
                  </div>
                  {patchResult && (
                    <div
                      style={{
                        marginTop: 8,
                        padding: "8px 10px",
                        background: "#ecfeff",
                        border: "1px solid #bae6fd",
                        borderRadius: 8,
                        color: "#075985",
                        fontSize: 13,
                        display: "flex",
                        flexDirection: "column",
                        gap: 4,
                      }}
                    >
                      <div>
                        Applied:{" "}
                        {patchResult.applied === false ? "❌ Not applied" : "✅ Applied"}
                      </div>
                      {Array.isArray(patchResult.files_changed) &&
                        patchResult.files_changed.length > 0 && (
                          <div>
                            Files: {patchResult.files_changed.slice(0, 5).join(", ")}
                            {patchResult.files_changed.length > 5 ? " …" : ""}
                          </div>
                        )}
                      {patchResult.head_sha_after && (
                        <div>New SHA: {patchResult.head_sha_after}</div>
                      )}
                      {patchResult.summary && <div>Summary: {patchResult.summary}</div>}
                    </div>
                  )}
                  {task.error && (
                    <div
                      style={{
                        marginTop: 8,
                        padding: "6px 8px",
                        background: "#fef2f2",
                        border: "1px solid #fecaca",
                        borderRadius: 6,
                        color: "#b91c1c",
                        fontSize: 13,
                      }}
                    >
                      {task.error_code ? `${task.error_code}: ` : ""}
                      {typeof task.error === "string"
                        ? task.error
                        : JSON.stringify(task.error)}
                    </div>
                  )}
                  {resultPreview && (
                    <div style={{ marginTop: 8 }}>
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedResults((prev) => ({
                            ...prev,
                            [key]: !prev[key],
                          }))
                        }
                        style={{
                          border: "1px solid #e5e7eb",
                          background: "#fff",
                          padding: "6px 8px",
                          borderRadius: 6,
                          fontSize: 12,
                          cursor: "pointer",
                        }}
                      >
                        {expandedResults[key] ? "Hide result" : "View result"}
                      </button>
                      {expandedResults[key] && (
                        <pre
                          style={{
                            marginTop: 6,
                            maxHeight: 200,
                            overflow: "auto",
                            background: "#f1f5f9",
                            padding: 8,
                            borderRadius: 6,
                            fontSize: 12,
                            whiteSpace: "pre-wrap",
                          }}
                        >
                          {resultPreview.slice(0, 2000)}
                        </pre>
                      )}
                    </div>
                  )}
                  {!resultPreview && isTerminal && !isError && (
                    <div style={{ marginTop: 8, fontSize: 12, color: "#334155" }}>
                      No result payload returned.
                    </div>
                  )}
                </div>
              </div>
            );
          }

          return (
            <ChatBubble
              key={key}
              sender={m.sender}
              text={m.text}
              metadata={m.metadata}
            />
          );
        })}
        {roomError && (
          <div className="status-bubble error">
            <span>{roomError}</span>
          </div>
        )}
        {status && (
          <div className="status-bubble">
            <span>{status}</span>
            <span className="status-dots">
              <span></span>
              <span></span>
              <span></span>
            </span>
          </div>
        )}
        {sendError && (
          <div className="status-bubble error">
            <span>Send failed ({sendError}) — check console/network</span>
          </div>
        )}
      </div>

      <ContextUsedDrawer
        preview={selectedPreviewMsgId ? contextByMsgId[selectedPreviewMsgId] : null}
        disabled={!previewEnabled}
        assistantMessages={messages
          .map((m, idx) => ({
            id: m.id || `${idx}`,
            snippet: (m.text || "").slice(0, 40) || "Assistant response",
            role: m.role,
          }))
          .filter((m) => m.role === "assistant")}
        selectedMessageId={selectedPreviewMsgId}
        onSelectMessage={(id) => setSelectedPreviewMsgId(id)}
      />

      {extensionBanner && (
        <div className="status-bubble warning">
          <span>{extensionBanner}</span>
        </div>
      )}

      {conflictHint && (
        <div className="status-bubble" style={{
          background: "#fef3c7",
          borderColor: "#f59e0b",
          color: "#92400e",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8
        }}>
          <span>⚠️ {conflictHint.message}</span>
          <button
            onClick={() => {
              setConflictHint(null);
              if (conflictHintTimeoutRef.current) {
                clearTimeout(conflictHintTimeoutRef.current);
              }
            }}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              fontSize: 18,
              padding: "0 4px",
              color: "#92400e",
              fontWeight: "bold"
            }}
            type="button"
            aria-label="Dismiss conflict hint"
          >
            ×
          </button>
        </div>
      )}
      {smokeResult && (
        <div
          className="status-bubble"
          style={{
            background: smokeResult.ok ? "#ecfdf3" : "#fef2f2",
            borderColor: smokeResult.ok ? "#4ade80" : "#fca5a5",
            color: smokeResult.ok ? "#166534" : "#991b1b",
          }}
        >
          <span>{smokeResult.message}</span>
        </div>
      )}

      {diagnosticsMode && lastDiagnostics && (
        <div className="diagnostics-panel">
          <div><strong>Diagnostics</strong></div>
          <div>classification: {lastDiagnostics.classification || "UNKNOWN"}</div>
          <div>client_request_id: {lastDiagnostics.client_request_id || "n/a"}</div>
          <div>server_request_id: {lastDiagnostics.server_request_id || "n/a"}</div>
          <div>status: {lastDiagnostics.status ?? "n/a"}</div>
          <div>elapsed_ms: {lastDiagnostics.elapsed_ms ?? "n/a"}</div>
          {lastDiagnostics.bodyPreview && (
            <pre className="diagnostics-body">{lastDiagnostics.bodyPreview}</pre>
          )}
        </div>
      )}

      {/* Notification Banner - shows above input but outside sticky container */}
      <NotificationBanner
        user={user}
        onRequestSummary={handleNotificationSummary}
      />

      <form className="input-container" onSubmit={handleSubmit}>

        <div style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "flex-end", marginBottom: 6, gap: 8, flexWrap: "wrap" }}>
          <div
            style={{
              display: "inline-flex",
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              overflow: "hidden",
            }}
          >
            {[
              { value: "site", label: "Site" },
              { value: "agent", label: "Agent (VS Code)" },
              { value: "patch", label: "Patch" },
            ].map((mode) => (
              <button
                key={mode.value}
                type="button"
                onClick={() => {
                  setSendMode(mode.value);
                  setPatchError("");
                  const key = `${sendModeKeyPrefix}${chatId || "default"}`;
                  try {
                    localStorage.setItem(key, mode.value);
                  } catch {
                    // ignore
                  }
                }}
                style={{
                  padding: "6px 10px",
                  fontSize: 12,
                  border: "none",
                  background: sendMode === mode.value ? "#eef2ff" : "#fff",
                  color: sendMode === mode.value ? "#3730a3" : "#111827",
                  cursor: "pointer",
                }}
              >
                {mode.label}
              </button>
            ))}
          </div>
          {sendMode !== "site" && repoOptions.length > 0 && (
            <select
              value={selectedRepoId || ""}
              onChange={(e) => setSelectedRepoId(e.target.value || null)}
              style={{ fontSize: 12 }}
            >
              <option value="">Select repo</option>
              {repoOptions.map((r) => (
                <option key={r.id || r.repo_id} value={r.id || r.repo_id}>
                  {r.name || r.repo || r.id}
                </option>
              ))}
            </select>
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
            <input
              type="checkbox"
              checked={previewEnabled}
              onChange={(e) => {
                const next = e.target.checked;
                setPreviewEnabled(next);
                try {
                  localStorage.setItem(previewToggleKey, next ? "1" : "0");
                } catch {
                  // ignore
                }
              }}
            />
            Include context preview
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
            <input
              type="checkbox"
              checked={diagnosticsMode}
              onChange={(e) => {
                const next = e.target.checked;
                setDiagnosticsMode(next);
                try {
                  localStorage.setItem(diagToggleKey, next ? "1" : "0");
                } catch {
                  // ignore
                }
              }}
            />
            Diagnostics mode
          </label>
          {sendMode !== "site" && (
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
              <input
                type="checkbox"
                checked={autoSurfaceUpdates}
                onChange={(e) => {
                  const next = e.target.checked;
                  setAutoSurfaceUpdates(next);
                  try {
                    localStorage.setItem("CHAT_AUTO_UPDATES", next ? "1" : "0");
                  } catch {
                    // ignore
                  }
                }}
              />
              Auto-surface updates
            </label>
          )}
          {diagnosticsMode && (
            <button
              type="button"
              onClick={runSmokeTest}
              disabled={smokeRunning}
              style={{
                border: "1px solid #e5e7eb",
                background: smokeRunning ? "#f8fafc" : "#fff",
                padding: "6px 10px",
                borderRadius: 8,
                cursor: smokeRunning ? "wait" : "pointer",
                fontSize: 12,
              }}
            >
              {smokeRunning ? "Smoke…" : "Smoke test"}
            </button>
          )}
        </div>

        {sendMode !== "site" && (
          <div style={{ width: "100%", display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={handleCheckUpdates}
              disabled={codeUpdatesLoading}
              style={{
                border: "1px solid #e5e7eb",
                background: "#fff",
                padding: "6px 10px",
                borderRadius: 8,
                cursor: codeUpdatesLoading ? "wait" : "pointer",
                fontSize: 12,
              }}
            >
              {codeUpdatesLoading ? "Checking updates..." : "Check updates"}
            </button>
            {newUpdatesCount > 0 && (
              <span
                style={{
                  background: "#eef2ff",
                  color: "#312e81",
                  padding: "4px 8px",
                  borderRadius: 999,
                  fontSize: 12,
                }}
              >
                New updates available ({newUpdatesCount})
              </span>
            )}
          </div>
        )}

        {sendMode === "patch" && (
          <div
            style={{
              width: "100%",
              marginBottom: 10,
              padding: "12px",
              border: "1px solid #e5e7eb",
              borderRadius: 10,
              background: "#f8fafc",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong>Apply patch (VS Code agent)</strong>
              <span style={{ fontSize: 12, color: "#475569" }}>Unified diff · max 200KB</span>
            </div>
            <textarea
              value={patchDiff}
              onChange={(e) => setPatchDiff(e.target.value)}
              placeholder="Paste unified diff here..."
              style={{
                width: "100%",
                minHeight: 140,
                fontFamily: "monospace",
                fontSize: 12,
                padding: 10,
                borderRadius: 8,
                border: "1px solid #e2e8f0",
                background: "#fff",
              }}
            />
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <input
                value={patchBaseSha}
                onChange={(e) => setPatchBaseSha(e.target.value)}
                placeholder="Base commit SHA (optional)"
                style={{
                  flex: "1 1 220px",
                  padding: "8px 10px",
                  borderRadius: 8,
                  border: "1px solid #e2e8f0",
                  fontSize: 12,
                }}
              />
              <input
                value={patchFiles}
                onChange={(e) => setPatchFiles(e.target.value)}
                placeholder="Files (optional, comma-separated)"
                style={{
                  flex: "1 1 220px",
                  padding: "8px 10px",
                  borderRadius: 8,
                  border: "1px solid #e2e8f0",
                  fontSize: 12,
                }}
              />
              <button
                type="button"
                onClick={sendPatch}
                style={{
                  border: "1px solid #e5e7eb",
                  background: "#fff",
                  padding: "8px 12px",
                  borderRadius: 8,
                  fontSize: 12,
                  cursor: "pointer",
                }}
              >
                Send patch
              </button>
            </div>
            {patchError && (
              <div style={{ color: "#b91c1c", fontSize: 13 }}>{patchError}</div>
            )}
          </div>
        )}

        {sendMode !== "site" && codeUpdatesVisible && (
          <div
            style={{
              width: "100%",
              marginBottom: 10,
              padding: "12px",
              border: "1px solid #e5e7eb",
              borderRadius: 10,
              background: "#f8fafc",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <div>
                <strong>Recent code updates</strong>
                {lastUpdateFilters && (
                  <div style={{ fontSize: 12, color: "#475569", marginTop: 2 }}>
                    Filters:
                    {lastUpdateFilters.focus_systems?.length > 0
                      ? ` ${lastUpdateFilters.focus_systems.join(", ")}`
                      : " none"}
                    {lastUpdateFilters.focus_impacts?.length > 0 && (
                      <> | impacts: {lastUpdateFilters.focus_impacts.join(", ")}</>
                    )}
                    {lastUpdateFilters.focus_files?.length > 0 && (
                      <> | files: {lastUpdateFilters.focus_files.slice(0, 2).join(", ")}</>
                    )}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => setCodeUpdatesVisible(false)}
                style={{
                  border: "none",
                  background: "transparent",
                  cursor: "pointer",
                  fontSize: 14,
                }}
                aria-label="Close updates panel"
              >
                ✕
              </button>
            </div>
            {codeUpdatesError && (
              <div style={{ marginTop: 8, color: "#b91c1c", fontSize: 13 }}>
                {codeUpdatesError}
              </div>
            )}
            {!codeUpdatesLoading && codeUpdates.length === 0 && !codeUpdatesError && (
              <div style={{ marginTop: 8, fontSize: 13, color: "#475569" }}>
                No recent updates.
              </div>
            )}
            {codeUpdatesLoading && (
              <div style={{ marginTop: 8, fontSize: 13, color: "#475569" }}>
                Loading…
              </div>
            )}
            {codeUpdates.length > 0 && (
              <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
                {codeUpdates.slice(0, 10).map((ev, idx) => (
                  <div
                    key={ev.id || ev.event_id || idx}
                    style={{
                      padding: "8px 10px",
                      borderRadius: 8,
                      background: "#fff",
                      border: "1px solid #e2e8f0",
                    }}
                  >
                    <div style={{ fontWeight: 600, marginBottom: 4 }}>
                      {ev.summary || ev.title || "Code event"}
                    </div>
                    <div style={{ fontSize: 12, color: "#475569" }}>
                      {ev.user_name || ev.user_id || "someone"} ·{" "}
                      {formatRelativeTime(ev.created_at || ev.timestamp)}
                    </div>
                    {Array.isArray(ev.impact_tags) && ev.impact_tags.length > 0 && (
                      <div style={{ marginTop: 4, display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {ev.impact_tags.map((tag, tIdx) => (
                          <span
                            key={`${tag}-${tIdx}`}
                            style={{
                              fontSize: 11,
                              background: "#eef2ff",
                              color: "#3730a3",
                              padding: "2px 6px",
                              borderRadius: 999,
                            }}
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
              <button
                type="button"
                onClick={handleMarkUpdatesSeen}
                style={{
                  border: "1px solid #e5e7eb",
                  background: "#fff",
                  padding: "6px 10px",
                  borderRadius: 8,
                  fontSize: 12,
                  cursor: "pointer",
                }}
              >
                Mark seen
              </button>
              <button
                type="button"
                onClick={handleCheckUpdates}
                disabled={codeUpdatesLoading}
                style={{
                  border: "1px solid #e5e7eb",
                  background: "#fff",
                  padding: "6px 10px",
                  borderRadius: 8,
                  fontSize: 12,
                  cursor: codeUpdatesLoading ? "wait" : "pointer",
                }}
              >
                Refresh
              </button>
            </div>
          </div>
        )}

        {teamUpdatesCount > 0 && (
          <div
            className="team-updates-banner"
            onClick={handleViewTeamUpdates}
            style={{
              width: "100%",
              marginBottom: 8,
              padding: "10px 12px",
              borderRadius: 8,
              background: "#eef2ff",
              color: "#1e3a8a",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            📬 {teamUpdatesCount} new team updates - Click to see summary →
          </div>
        )}
        {showTeamSummary && teamSummary && (
          <div
            className="team-updates-summary"
            style={{
              width: "100%",
              marginBottom: 8,
              padding: "12px",
              border: "1px solid #e5e7eb",
              borderRadius: 10,
              background: "#fff",
              boxShadow: "0 6px 18px rgba(0,0,0,0.06)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong>Team updates summary</strong>
              <button
                type="button"
                onClick={() => setShowTeamSummary(false)}
                style={{
                  border: "none",
                  background: "transparent",
                  cursor: "pointer",
                  fontSize: 14,
                }}
                aria-label="Close summary"
              >
                ✕
              </button>
            </div>
            <p style={{ marginTop: 6, marginBottom: 0 }}>
              {teamSummary.summary || "No summary available."}
            </p>
          </div>
        )}
        {ragInfo && (
          <div className={`rag-indicator rag-${ragInfo.status}`}>
            {ragInfo.status === "searching" && (
              <>
                <span className="rag-spinner">🔍</span>
                <span>{ragInfo.reason}...</span>
              </>
            )}
            {ragInfo.status === "found" && (
              <>
                <span className="rag-icon">✓</span>
                <span>
                  Found {ragInfo.count} relevant messages from history
                </span>
              </>
            )}
            {ragInfo.status === "none" && (
              <>
                <span className="rag-icon">ℹ️</span>
                <span>No relevant history found - using recent context</span>
              </>
            )}
          </div>
        )}
        {uploadPreviews.length > 0 && (
          <div className="file-previews">
            {uploadPreviews.map((preview, index) => (
              <div key={index} className="file-preview-item">
                {preview.type === "image" ? (
                  <img
                    src={preview.url}
                    alt={preview.name}
                    className="preview-image"
                  />
                ) : (
                  <div className="preview-file">
                    📄 {preview.name}
                    <span className="file-size">{preview.size}</span>
                  </div>
                )}
                <button
                  type="button"
                  className="remove-file-btn"
                  onClick={() => removeFile(index)}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="input-row">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileSelect}
            accept="image/*,.pdf,.txt,.md,.csv,.json,.py,.js,.jsx,.ts,.tsx,.html,.css"
            multiple
            style={{ display: "none" }}
          />
          <button
            type="button"
            className="attach-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={!chatId}
          >
            📎
          </button>
          <input
            className="chat-input"
            placeholder="Ask Parallel OS..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={!chatId}
          />
          <button
            type="submit"
            className="chat-send"
            disabled={
              (!input.trim() && selectedFiles.length === 0) || !chatId
            }
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
