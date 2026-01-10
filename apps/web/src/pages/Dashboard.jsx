import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import "./Dashboard.css";
import Sidebar from "../components/Sidebar";
import ChatPanel from "../components/ChatPanel";
import { GitTextEditorPanel } from "../features/ide/GitTextEditorPanel";
import Manager from "./Manager";
import { fetchTeam, getChatMessages, createChat, listAllChats } from "../lib/tasksApi";
import { API_BASE_URL } from "../config";
import Timeline from "./Timeline";
import SettingsPage from "./SettingsPage";
import VscodePage from "./VscodePage";
import RightSidebarPanel from "../components/RightSidebarPanel";
import { logger } from "../utils/logger";

// Module-level diagnostics to help trace TDZ/cycle issues
console.info("[Dashboard] module init", {
  listAllChatsType: typeof listAllChats,
  createChatType: typeof createChat,
  sidebarImported: !!Sidebar,
  chatPanelImported: !!ChatPanel,
});
function InboxView({ inbox, onTogglePin }) {
  return (
    <div className="chat-wrapper glass">
      <div className="panel-head">
        <div>
          <p className="eyebrow">Inbox</p>
          <h2>Captured tasks</h2>
        </div>
      </div>
      {inbox.length === 0 && <p className="subhead">No tasks yet.</p>}
      <div className="inbox-list">
        {inbox.map((task) => (
          <div className={`inbox-item ${task.status === "done" ? "done" : ""}`} key={task.id}>
            <div className="inbox-title">
              {task.content}
              {task.pinned && (
                <span className="status-pill subtle" style={{ marginLeft: 8 }}>
                  Pinned
                </span>
              )}
              {Array.isArray(task.tags) && task.tags.includes("auto") && (
                <span className="status-pill subtle" style={{ marginLeft: 8 }}>
                  Auto
                </span>
              )}
              {Array.isArray(task.tags) && task.tags.includes("self-reminder") && (
                <span className="status-pill subtle" style={{ marginLeft: 8 }}>
                  Self reminder
                </span>
              )}
              {task.room_name && (
                <span className="status-pill subtle" style={{ marginLeft: 8 }}>
                  From {task.room_name}
                </span>
              )}
            </div>
            <div className="inbox-meta">
              <span>{task.status}</span>
              {task.priority && <span>{task.priority}</span>}
              <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
                <button
                  className="btn"
                  style={{ padding: "4px 8px" }}
                  onClick={() => onTogglePin(task)}
                >
                  {task.pinned ? "Unpin" : "Pin"}
                </button>
                {task.status !== "done" && (
                  <button
                    className="btn"
                    style={{ padding: "4px 8px" }}
                    onClick={() => onTogglePin(task, true)}
                  >
                    Mark done
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function IdeView() {
  return <GitTextEditorPanel />;
}

// ----- Main dashboard -----

export default function Dashboard({ user: propUser }) {
  const navigate = useNavigate();
  const location = useLocation();
  // Derived route flags must stay directly after hooks so deps arrays don't touch TDZ bindings
  const isSettings = location.pathname.startsWith("/app/settings");
  const isVscode = location.pathname.startsWith("/app/vscode");
  const [liveLog, setLiveLog] = useState([]);
  const [chatStyle, setChatStyle] = useState("windowed"); // "windowed" | "glass" | "bare"

  // User / auth - use prop if provided, otherwise fetch
  const [user, setUser] = useState(propUser || null);
  const [loadingUser, setLoadingUser] = useState(!propUser);
  const [userError, setUserError] = useState("");
  const [workspaceId, setWorkspaceId] = useState(null);

  // Room
  const [roomId] = useState(null);
  const [roomData] = useState(null);
  const [roomError] = useState("");
  const [loadingRoom, setLoadingRoom] = useState(true);

  // UI state
  const [activeTool, setActiveTool] = useState("Timeline");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => JSON.parse(localStorage.getItem("sidebarCollapsed") || "false")
  );
  const [rightRatio, setRightRatio] = useState(0.35); // fraction for right panel
  const [lastRightRatio, setLastRightRatio] = useState(0.35);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [rightSidebarView, setRightSidebarView] = useState("summary");
  const containerRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const rightCollapseTimer = useRef(null);
  const messagesEffectInitial = useRef(true);

  // Activity / team / inbox
  const [activityLog, setActivityLog] = useState([]);
  const [teamMembers, setTeamMembers] = useState([]);
  const [teamStatuses, setTeamStatuses] = useState([]);
  const [selectedRoomId] = useState(null);

  const { chatId } = useParams();

  const [selectedChatId, setSelectedChatId] = useState(chatId || null);

  const [messagesByChat, setMessagesByChat] = useState({});
  const [loadingChat, setLoadingChat] = useState(false);
  const [chatError, setChatError] = useState("");
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const chatsCountRef = useRef(0);
  const CHAT_STORAGE_KEY = "selectedChatId";
  const [chats, setChats] = useState([]);
  const [chatLoadError, setChatLoadError] = useState(null);
  const [experimentalChats, setExperimentalChats] = useState([]);
  const lastExperimentalWorkspaceRef = useRef(null);

  const handleAutoRefreshHistory = useCallback(() => {
    setHistoryRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    logger.debug("🔍 [DASHBOARD STATE]", {
      chatsCount: chats.length,
      chats: chats,
      selectedChatId,
      activeTool  // ← Changed from activeSection
    });
  }, [chats, selectedChatId, activeTool]);

  useEffect(() => {
    logger.debug("[Dashboard] User:", user);
    logger.debug("[Dashboard] Chats:", chats);
    logger.debug("[Dashboard] Selected chat:", selectedChatId);
  }, [user, chats, selectedChatId]);

  // Add this after const [chats, setChats] = useState([]);
  useEffect(() => {
    logger.debug("🔍 [CHATS STATE CHANGED]", {
      count: chats.length,
      firstChat: chats[0],
      allChatIds: chats.map(c => c.id || c.chat_id)
    });
  }, [chats]);

  const loadChatsWithRetry = useCallback(async () => {
    if (!workspaceId) {
      logger.debug("📥 [LOAD CHATS] Skipping - no workspaceId yet");
      return;
    }
    setChatLoadError(null);
    const delays = [0, 500, 1500];
    let lastErr = null;
    let finalList = null;
    for (let i = 0; i < delays.length; i++) {
      if (delays[i] > 0) {
        await new Promise((r) => setTimeout(r, delays[i]));
      }
      try {
        logger.debug("📥 [LOAD CHATS RETRY] attempt", i + 1);
        const data = await listAllChats(workspaceId, { useGlobal: true });
        const normalizedChats = Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : [];
        finalList = normalizedChats;
        chatsCountRef.current = normalizedChats.length;
        lastErr = null;
        break;
      } catch (err) {
        lastErr = err;
        logger.error("❌ [LOAD CHATS] attempt failed:", err);
      }
    }
    if (lastErr) {
      setChatLoadError({
        message: lastErr?.message || "Chats failed to load",
        request_id: lastErr?.request_id,
      });
      return;
    }
    if (finalList) {
      setChats(finalList);
      const stored = localStorage.getItem(CHAT_STORAGE_KEY);
      const storedValid = stored && finalList.some((c) => (c.id || c.chat_id) === stored);
      if (chatId && finalList.some((c) => (c.id || c.chat_id) === chatId)) {
        setSelectedChatId(chatId);
        localStorage.setItem(CHAT_STORAGE_KEY, chatId);
      } else if (!selectedChatId && finalList.length > 0) {
        const nextId = storedValid
          ? stored
          : finalList[0].id || finalList[0].chat_id;
        if (nextId) {
          setSelectedChatId(nextId);
          localStorage.setItem(CHAT_STORAGE_KEY, nextId);
          if (activeTool === "Chat" || location.pathname.includes(`/chat/${nextId}`)) {
            setActiveTool("Chat");
            if (!isSettings && !location.pathname.includes(`/chat/${nextId}`)) {
              navigate(`/app/chat/${nextId}`);
            }
          }
        }
      }
    }
  }, [
    activeTool,
    chatId,
    isSettings,
    location.pathname,
    navigate,
    selectedChatId,
    workspaceId,
  ]); // isSettings must stay declared above to avoid TDZ on bootstrap

  const createNewChat = useCallback(
    async (name) => {
      try {
        const fallbackName = name && name.trim() ? name.trim() : `Chat ${chatsCountRef.current + 1}`;
        const newChat = await createChat(fallbackName);
        const id = newChat.id || newChat.chat_id;
        if (id) {
          chatsCountRef.current += 1;
          setSelectedChatId(id);
          setMessagesByChat((prev) => ({ ...prev, [id]: [] }));
          setActiveTool("Chat");
          localStorage.setItem(CHAT_STORAGE_KEY, id);
          navigate(`/app/chat/${id}`);
        }
    } catch (err) {
      console.error("Failed to create chat", err);
      alert("Failed to create chat. Please try again.");
    }
  },
  [navigate]
);

  const handleChatSelect = (chat) => {
    const id = chat.id || chat.chat_id;
    if (!id) return;
    setSelectedChatId(id);
    localStorage.setItem(CHAT_STORAGE_KEY, id);
    setActiveTool("Chat");
    navigate(`/app/chat/${id}`);
  };

  const handleChatCreate = async (chatData) => {
    // Add new chat to the list
    setChats((prev) => [chatData, ...prev]);
    
    // Then select it
    handleChatSelect(chatData);
  };

  const handleExperimentalSelect = useCallback(async (entry) => {
    const rawId = entry?.id || entry?.chat_id || "";
    const match = typeof rawId === "string" ? rawId.match(/^system-agent-(.+)$/) : null;
    const parsedId = match ? match[1] : null;
    const agentId = parsedId || entry?.agent_id;

    if (agentId) {
      navigate(`/graphs/${agentId}`);
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/graphs/me`, { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        const fallbackId = data?.agent_id || data?.id;
        if (fallbackId) {
          navigate(`/graphs/${fallbackId}`);
          return;
        }
      }
    } catch (err) {
      logger.warn("[Dashboard] Experimental agent lookup failed", err);
    }

    navigate("/graphs");
  }, [navigate]);

  useEffect(() => {
    if (!workspaceId) {
      setExperimentalChats([]);
      lastExperimentalWorkspaceRef.current = null;
      return;
    }
    if (lastExperimentalWorkspaceRef.current === workspaceId) return;

    let cancelled = false;
    lastExperimentalWorkspaceRef.current = workspaceId;

    const loadExperimental = async () => {
      try {
        const data = await listAllChats(workspaceId);
        const items = Array.isArray(data?.items) ? data.items : [];
        const experimentalOnly = items.filter((chat) => {
          const idVal = chat?.id || chat?.chat_id || "";
          const nameVal = chat?.name || chat?.chat_name;
          return (
            (typeof idVal === "string" && idVal.startsWith("system-agent-")) ||
            nameVal === "🧪 System Agent (Experimental)"
          );
        });
        if (!cancelled) {
          setExperimentalChats(experimentalOnly);
        }
      } catch (err) {
        if (!cancelled) {
          logger.warn("[Dashboard] Experimental chat load failed (non-blocking)", err);
          setExperimentalChats([]);
        }
      }
    };

    loadExperimental();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  useEffect(() => {
    if (!roomData || !Array.isArray(roomData.messages)) {
      setLiveLog([]);
      return;
    }
  
    const latestBySender = {};
  
    for (const msg of roomData.messages) {
      if (msg.role !== "user") continue;
  
      const key = msg.sender_id || msg.sender_name || "unknown";
      if (
        !latestBySender[key] ||
        new Date(msg.created_at) > new Date(latestBySender[key].created_at)
      ) {
        latestBySender[key] = msg;
      }
    }
  
    const entries = Object.values(latestBySender)
      .map((msg) => ({
        id: msg.id,
        name: msg.sender_name || "Teammate",
        content: msg.content || "",
        at: msg.created_at,
      }))
      .sort((a, b) => new Date(b.at) - new Date(a.at));
  
    setLiveLog(entries);
  }, [roomData]);

  useEffect(() => {
    // Skip fetching if user was provided via props
    if (propUser) {
      setUser({
        id: propUser.id,
        name: propUser.name || propUser.email || "You",
        email: propUser.email,
        role: propUser.role,
        is_platform_admin: propUser.is_platform_admin,
        org_id: propUser.org_id,
      });
      setLoadingUser(false);
      return;
    }

    const fetchMe = async () => {
      try {
        setLoadingUser(true);
        const res = await fetch(`${API_BASE_URL}/api/me`, {
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          console.log("🔍 /api/me response:", data);
          setUser({
            id: data.id,
            name: data.name || data.email || "You",
            email: data.email,
            role: data.role,
            is_platform_admin: data.is_platform_admin,
            org_id: data.org_id,
          });
          setUserError("");
        } else {
          const text = await res.text();
          console.error("Failed /me", res.status, text);
          setUser(null);
          setUserError("Not logged in.");
        }
      } catch (err) {
        console.error("Error fetching /me", err);
        setUserError("Failed to reach server.");
      } finally {
        setLoadingUser(false);
      }
    };

    fetchMe();
  }, [propUser]);

  // Fetch workspaces when user is loaded
  useEffect(() => {
    if (!user?.org_id) return;

    const fetchWorkspaces = async () => {
      try {
        logger.debug("[Dashboard] Fetching workspaces for org:", user.org_id);
        const res = await fetch(`${API_BASE_URL}/api/v1/workspaces`, {
          credentials: "include",
        });

        if (res.ok) {
          const workspaces = await res.json();
          logger.debug("[Dashboard] Workspaces response:", workspaces);

          // Get the first workspace ID
          if (Array.isArray(workspaces) && workspaces.length > 0) {
            const firstWorkspace = workspaces[0];
            const wsId = firstWorkspace.id || firstWorkspace.workspace_id;
            logger.debug("[Dashboard] Setting workspace_id:", wsId);
            setWorkspaceId(wsId);
          } else {
            logger.warn("[Dashboard] No workspaces found");
          }
        } else {
          logger.error("[Dashboard] Failed to fetch workspaces:", res.status);
        }
      } catch (err) {
        logger.error("[Dashboard] Error fetching workspaces:", err);
      }
    };

    fetchWorkspaces();
  }, [user?.org_id]);

  useEffect(() => {
    if (!user) return;

    const loadTeam = async () => {
      try {
        const members = (await fetchTeam()) || [];
        setTeamMembers(members);
      } catch (err) {
        console.error("Failed to load team for activity view", err);
      }
    };

    loadTeam();
    const id = setInterval(loadTeam, 10000);
    return () => clearInterval(id);
  }, [user]);

  useEffect(() => {
    if (chatId && chatId !== selectedChatId) {
      setSelectedChatId(chatId);
    }
  }, [chatId, selectedChatId]);

  const loadMessagesForChat = useCallback(
    async (chatId) => {
      if (!chatId) return;
      console.group("📨 [LOAD MESSAGES] Fetching history");
      console.log("chatId:", chatId);
      console.log("Is this initial mount?", messagesEffectInitial.current);
      try {
        setLoadingChat(true);
        setChatError("");

        console.log("🔷 Calling getChatMessages...");
        const data = await getChatMessages(chatId);

        console.log("✅ Messages loaded:", data);
        // FIX: Backend returns {chat: {...}, messages: [...]}
        const messages = Array.isArray(data)
          ? data
          : Array.isArray(data?.messages)
          ? data.messages
          : [];
        console.log("Message count:", messages.length);
        if (messages.length > 0) {
          console.log("First message:", messages[0]);
          console.log("Last message:", messages[messages.length - 1]);
        }

        setMessagesByChat((prev) => ({
          ...prev,
          [chatId]: messages,
        }));
      } catch (err) {
        console.error("❌ Failed to load messages:", err);
        console.error("Error details:", err.message);
        setChatError(`Failed to load messages: ${err.message}`);
        setMessagesByChat((prev) => ({
          ...prev,
          [chatId]: [],
        }));
      } finally {
        setLoadingChat(false);
        console.groupEnd();
        messagesEffectInitial.current = false;
      }
    },
    []
  );

  useEffect(() => {
    if (!selectedChatId) {
      console.group("📨 [LOAD MESSAGES] Effect triggered");
      console.log("selectedChatId:", selectedChatId);
      console.log("No chat selected, clearing messages");
      console.groupEnd();
      setMessagesByChat({});
      messagesEffectInitial.current = false;
      return;
    }

    loadMessagesForChat(selectedChatId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedChatId]);

  // Rooms are no longer user-facing; skip auto-select by room to avoid 403s

  // useEffect(() => {
  //   console.log("🔍 [DASHBOARD STATE]", {
  //     chatsCount: chats.length,
  //     chats: chats,
  //     selectedChatId,
  //     activeSection
  //   });
  // }, [chats, selectedChatId, activeSection]);

  useEffect(() => {
    if (!user) return;

    const label =
      activeTool === "IDE"
        ? "Development"
        : activeTool === "History"
        ? "Activity history"
        : activeTool === "Inbox"
        ? "Inbox review"
        : activeTool === "Team"
        ? "Team activity"
        : "In chat";

    const entry = {
      id: `${Date.now()}`,
      state: label,
      detail: `Switched to ${activeTool}`,
      at: new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
      name: user.name || "You",
    };
    setActivityLog((prev) => [entry, ...prev].slice(0, 6));

    const roomMembers =
      (Array.isArray(roomData?.members) && roomData.members.length > 0
        ? roomData.members
        : teamMembers.length > 0
        ? teamMembers
        : [user]
      ).filter(Boolean);

    const seen = new Set();
    const uniqueMembers = [];
    for (const m of roomMembers) {
      const key = m.id || m.user_id || m.userId || m.email || m.name;
      if (key && seen.has(key)) continue;
      if (key) seen.add(key);
      uniqueMembers.push(m);
    }

    const statuses = uniqueMembers.map((m) => {
      const memberId = m.id || m.user_id || m.userId;
      const isSelf = memberId && memberId === user.id;
      const displayName = m.name || m.email || "Teammate";
      const primaryRole =
        (Array.isArray(m.roles) && m.roles[0]) || m.role || "Teammate";

      return {
        name: displayName,
        role: isSelf ? label : primaryRole,
        state: isSelf ? "active" : "online",
      };
    });

    setTeamStatuses(statuses);
  }, [activeTool, user, teamMembers, roomData]);

  // Room polling removed to avoid 403 when room is not accessible; chats are roomless in UI

  useEffect(() => {
    // No-op: room resolution disabled
    setLoadingRoom(false);
  }, []);

  // Load chats when workspace or critical dependencies change
  // Note: We don't depend on loadChatsWithRetry to avoid cascading re-renders
  useEffect(() => {
    loadChatsWithRetry();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  const handleLogout = async () => {
    try {
      await fetch(`${API_BASE_URL}/api/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // ignore
    } finally {
      window.location.reload();
    }
  };

  useEffect(() => {
    localStorage.setItem("sidebarCollapsed", JSON.stringify(sidebarCollapsed));
  }, [sidebarCollapsed]);

  useEffect(() => {
    const move = (e) => {
      if (!dragging || !containerRef.current || rightCollapsed) return;
      const rect = containerRef.current.getBoundingClientRect();
      const sidebarWidth = sidebarCollapsed ? 80 : 260;
      const usable = rect.width - sidebarWidth;
      const x = e.clientX - rect.left - sidebarWidth;
      const ratio = Math.min(Math.max(x / usable, 0.2), 0.6);
      setRightRatio(1 - ratio);
      setLastRightRatio(1 - ratio);
    };
    const up = () => setDragging(false);
    if (dragging) {
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    }
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
  }, [dragging, sidebarCollapsed, rightCollapsed]);

  useEffect(() => {
    return () => {
      if (rightCollapseTimer.current) clearTimeout(rightCollapseTimer.current);
    };
  }, []);

  const handleNavSelect = async (label) => {
    if (label === "NewChat") {
      const name = window.prompt("Name your chat", `Chat ${chatsCountRef.current + 1}`) || "";
      await createNewChat(name);
      return;
    }
    if (label === "Chat") {
      setActiveTool("Chat");
      if (!selectedChatId && chats.length > 0) {
        const firstId = chats[0]?.id || chats[0]?.chat_id;
        if (firstId) {
          setSelectedChatId(firstId);
          localStorage.setItem(CHAT_STORAGE_KEY, firstId);
          navigate(`/app/chat/${firstId}`);
        }
      }
      if (isSettings) {
        navigate("/app");
      }
      return;
    }
    setActiveTool(label);
    // Navigate back to /app when leaving Settings or VS Code
    if (isSettings || isVscode) {
      navigate("/app");
    }
  };

  const bumpHistory = () => setHistoryRefreshKey((k) => k + 1);

  const containerClass = sidebarCollapsed
    ? "dashboard-container collapsed"
    : "dashboard-container";
  const sidebarWidth = sidebarCollapsed ? "80px" : "260px";
  const chatFraction = rightCollapsed ? 1 : 1 - rightRatio;
  const containerStyle = {
    gridTemplateColumns: `${sidebarWidth} ${chatFraction}fr ${
      rightCollapsed ? "24px" : `${rightRatio}fr`
    }`,
  };

  const currentMessages = selectedChatId
    ? messagesByChat[selectedChatId] || []
    : [];

  useEffect(() => {
    // route-based chat selection
    const path = location.pathname;
    const match = path.match(/\/chat\/([^/]+)/);
    if (match && match[1] !== selectedChatId) {
      setSelectedChatId(match[1]);
      localStorage.setItem(CHAT_STORAGE_KEY, match[1]);
      setActiveTool("Chat");
    }
  }, [location.pathname, selectedChatId]);

  useEffect(() => {
    if (isVscode && activeTool !== "VS Code") {
      setActiveTool("VS Code");
    }
  }, [activeTool, isVscode]);

  const handleMessagesUpdate = useCallback(
    (chatIdFromChild, newMessages) => {
      const targetId = chatIdFromChild || selectedChatId;
      if (!targetId) return;
      console.log("Messages updated:", (newMessages || []).length, "for", targetId);
      setMessagesByChat((prev) => ({
        ...prev,
        [targetId]: newMessages || [],
      }));
    },
    [selectedChatId]
  );

  // Scroll handler removed - tabs now used for navigation

  const handleChatRename = (chatId, newName) => {
    setChats((prev) =>
      prev.map((c) =>
        (c.id || c.chat_id) === chatId
          ? { ...c, name: newName }
          : c
      )
    );
  };
  
  const handleChatDelete = (chatId) => {
    setChats((prev) =>
      prev.filter((c) => (c.id || c.chat_id) !== chatId)
    );
  };

  if (loadingUser) {
    return <div className="dashboard-loading">Loading your workspace…</div>;
  }

  if (!user) {
    return (
      <div className="dashboard-loading">
        {userError || "You're not logged in."}
      </div>
    );
  }

  if (loadingRoom && !roomId && !roomError) {
    return (
      <div className="dashboard-loading">
        Setting up your team room…
      </div>
    );
  }

  if (roomError && !roomId) {
    return (
      <div className="dashboard-loading">
        {roomError || "Could not load your team room."}
      </div>
    );
  }

  return (
    <div className={containerClass} style={containerStyle} ref={containerRef}>
      <Sidebar
        active={activeTool}
        onSelect={handleNavSelect}
        onToggle={() => setSidebarCollapsed((c) => !c)}
        onLogout={handleLogout}
        currentRoomId={selectedRoomId}
        currentUser={user}
        collapsed={sidebarCollapsed}
        onCollapseToggle={(next) =>
          setSidebarCollapsed((c) =>
            typeof next === "boolean" ? next : !c
          )
        }
        openRoomId={selectedChatId}
        onRoomClick={handleChatSelect}
        chats={chats}  // ADD THIS LINE
        onChatCreate={handleChatCreate}  // ADD THIS
        onChatRename={handleChatRename}  // ADD
        onChatDelete={handleChatDelete}  // ADD
        chatLoadError={chatLoadError}
        onChatRetry={loadChatsWithRetry}
        experimentalChats={experimentalChats}
        onExperimentalSelect={handleExperimentalSelect}
      />

      {isSettings ? (
        <div style={{ gridColumn: "span 2", width: "100%", padding: 12 }}>
          <SettingsPage />
        </div>
      ) : isVscode ? (
        <div style={{ gridColumn: "span 2", width: "100%", padding: 12 }}>
          <VscodePage user={user} />
        </div>
      ) : activeTool === "Manager" ? (
        <div style={{ gridColumn: "span 2", width: "100%" }}>
          <Manager currentUser={user} />
        </div>
      ) : activeTool === "Timeline" ? (
        <div
          style={{
            gridColumn: "span 2",
            width: "100%",
            padding: 12,
            overflowY: "auto",
            maxHeight: "100vh",
          }}
        >
          <Timeline onHistoryChange={bumpHistory} />
        </div>
      ) : (
        <>
          <div className="dashboard-main">
            <div className="chat-style-switch">
              <label className={`chat-style-pill ${chatStyle === "windowed" ? "active" : ""}`}>
                <input
                  type="radio"
                  name="chatStyle"
                  value="windowed"
                  checked={chatStyle === "windowed"}
                  onChange={() => setChatStyle("windowed")}
                />
                Classic
              </label>
              <label className={`chat-style-pill ${chatStyle === "glass" ? "active" : ""}`}>
                <input
                  type="radio"
                  name="chatStyle"
                  value="glass"
                  checked={chatStyle === "glass"}
                  onChange={() => setChatStyle("glass")}
                />
                Glass
              </label>
              <label className={`chat-style-pill ${chatStyle === "bare" ? "active" : ""}`}>
                <input
                  type="radio"
                  name="chatStyle"
                  value="bare"
                  checked={chatStyle === "bare"}
                  onChange={() => setChatStyle("bare")}
                />
                Minimal
              </label>
            </div>
            {chatError && (
              <div className="status-bubble error" style={{ marginBottom: 10 }}>
                {chatError}
              </div>
            )}
            <div className={`chat-container chat-${chatStyle}`}>
              <ChatPanel
                user={user}
                roomId={selectedRoomId || roomId}
                chatId={selectedChatId}
                initialMessages={currentMessages}
                onMessagesUpdate={handleMessagesUpdate}
              />
            </div>
            {loadingChat && (
              <div style={{ padding: "20px", textAlign: "center" }}>
                Loading messages...
              </div>
            )}
            {!loadingChat &&
              currentMessages.length === 0 &&
              selectedChatId &&
              !chatError && (
                <div
                  style={{
                    padding: "20px",
                    textAlign: "center",
                    color: "var(--text-muted)",
                  }}
                >
                  No messages yet. Start the conversation!
                </div>
              )}
          </div>
          {!isSettings && !isVscode && (
            <div
              className={`dashboard-right-wrapper ${
                rightCollapsed ? "collapsed" : ""
              }`}
              onMouseEnter={() => {
                if (rightCollapseTimer.current) {
                  clearTimeout(rightCollapseTimer.current);
                  rightCollapseTimer.current = null;
                }
                if (rightCollapsed) {
                  setRightCollapsed(false);
                  setRightRatio(lastRightRatio || 0.35);
                }
              }}
              onMouseLeave={() => {
                if (rightCollapseTimer.current) {
                  clearTimeout(rightCollapseTimer.current);
                  rightCollapseTimer.current = null;
                }
                rightCollapseTimer.current = setTimeout(() => {
                  setRightCollapsed(true);
                  setLastRightRatio(rightRatio || lastRightRatio || 0.35);
                  setRightRatio(0);
                }, 150);
              }}
            >
              {rightCollapsed ? (
                <div
                  className="right-tab"
                  title="Expand panel"
                  onMouseDown={() => {
                    setRightCollapsed(false);
                    setRightRatio(lastRightRatio || 0.35);
                    setDragging(true);
                  }}
                >
                  ‹
                </div>
              ) : (
                <>
                  <div
                    className="split-resizer"
                    onMouseDown={() => setDragging(true)}
                    title="Drag to resize"
                  />
                  <RightSidebarPanel
                    activeTool={activeTool}
                    rightSidebarView={rightSidebarView}
                    onRightSidebarViewChange={setRightSidebarView}
                    user={user}
                    teamStatuses={teamStatuses}
                    liveLog={liveLog}
                    activityLog={activityLog}
                    roomData={roomData}
                    historyRefreshKey={historyRefreshKey}
                    onAutoRefreshHistory={handleAutoRefreshHistory}
                  />
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
