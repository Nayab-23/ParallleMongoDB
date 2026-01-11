import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./DemoChat.css";
import UserPicker from "./UserPicker";
import {
  createChat,
  dispatchChat,
  getChatMessages,
  getMe,
  getTaskStatus,
  listChats,
} from "../api/demoApi";

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_ATTEMPTS = 60;

function normalizeChat(chat) {
  if (!chat) return null;
  return {
    id: chat.id || chat.chat_id,
    chat_id: chat.chat_id || chat.id,
    name: chat.name || "Chat",
    last_message_at: chat.last_message_at || chat.updated_at,
  };
}

function normalizeMessage(message) {
  if (!message) return null;
  return {
    id: message.message_id || message.id,
    role: message.role || "assistant",
    content: message.content || "",
    created_at: message.created_at,
  };
}

export default function DemoChat() {
  const [demoUser, setDemoUser] = useState(() => localStorage.getItem("demo_user"));
  const [user, setUser] = useState(null);
  const [userError, setUserError] = useState("");

  const [chats, setChats] = useState([]);
  const [selectedChatId, setSelectedChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [messagesLoading, setMessagesLoading] = useState(false);

  const [newChatName, setNewChatName] = useState("");
  const [creatingChat, setCreatingChat] = useState(false);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");

  const [taskStatusById, setTaskStatusById] = useState({});
  const [taskResultById, setTaskResultById] = useState({});

  const pollersRef = useRef({});

  const selectedChat = useMemo(() => {
    return chats.find((chat) => (chat.id || chat.chat_id) === selectedChatId) || null;
  }, [chats, selectedChatId]);

  const loadUser = useCallback(async () => {
    try {
      const data = await getMe();
      setUser(data);
    } catch (err) {
      setUserError("Failed to load demo user. Ensure the backend is running.");
      setUser({ id: "demo-user-1", name: "Demo User", workspace_id: "1" });
    }
  }, []);

  const loadChats = useCallback(
    async (nextChatId = null) => {
      try {
        const data = await listChats();
        const items = Array.isArray(data?.items) ? data.items : [];
        const normalized = items.map(normalizeChat).filter(Boolean);
        setChats(normalized);
        const initialId =
          nextChatId ||
          selectedChatId ||
          (normalized[0] ? normalized[0].id || normalized[0].chat_id : null);
        if (initialId) {
          setSelectedChatId(initialId);
        }
      } catch (err) {
        setChats([]);
      }
    },
    [selectedChatId]
  );

  const loadMessages = useCallback(async () => {
    if (!selectedChatId) {
      setMessages([]);
      return;
    }
    setMessagesLoading(true);
    try {
      const data = await getChatMessages(selectedChatId);
      const normalized = (Array.isArray(data) ? data : [])
        .map(normalizeMessage)
        .filter(Boolean);
      setMessages(normalized);
    } catch (err) {
      setMessages([]);
    } finally {
      setMessagesLoading(false);
    }
  }, [selectedChatId]);

  const pollTaskStatus = useCallback((taskId) => {
    if (!taskId || pollersRef.current[taskId]) {
      return;
    }

    let cancelled = false;
    pollersRef.current[taskId] = () => {
      cancelled = true;
    };

    const run = async () => {
      let attempts = 0;
      while (!cancelled && attempts < POLL_MAX_ATTEMPTS) {
        try {
          const data = await getTaskStatus(taskId);
          const status = data?.status || "pending";
          setTaskStatusById((prev) => ({ ...prev, [taskId]: status }));
          if (data?.result) {
            setTaskResultById((prev) => ({ ...prev, [taskId]: data.result }));
          }
          if (status === "done" || status === "error") {
            break;
          }
        } catch (err) {
          if (err?.status === 404) {
            break;
          }
        }
        attempts += 1;
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      }
      delete pollersRef.current[taskId];
    };

    run();
  }, []);

  const handleCreateChat = async (event) => {
    event.preventDefault();
    if (creatingChat) return;
    const name = newChatName.trim() || `Demo Chat ${chats.length + 1}`;
    setCreatingChat(true);
    try {
      const data = await createChat(name);
      const normalized = normalizeChat(data);
      setNewChatName("");
      await loadChats(normalized?.id || normalized?.chat_id || null);
    } catch (err) {
    } finally {
      setCreatingChat(false);
    }
  };

  const handleSend = async (event) => {
    event.preventDefault();
    if (!selectedChatId || sending) return;
    const trimmed = input.trim();
    if (!trimmed) return;

    setSending(true);
    setSendError("");
    setInput("");

    const localUserMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: trimmed,
      created_at: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, localUserMessage]);

    try {
      const data = await dispatchChat(selectedChatId, trimmed);
      const taskId = data?.task_id || data?.taskId || data?.id;
      if (taskId) {
        setTaskStatusById((prev) => ({ ...prev, [taskId]: data?.status || "pending" }));
        setMessages((prev) => [
          ...prev,
          {
            id: `task-${taskId}`,
            role: "assistant",
            content: "Sent to VS Code agent.",
            task_id: taskId,
            created_at: new Date().toISOString(),
          },
        ]);
        pollTaskStatus(taskId);
      }
      await loadChats(selectedChatId);
    } catch (err) {
      setSendError(err?.message || "Failed to dispatch task.");
    } finally {
      setSending(false);
    }
  };

  useEffect(() => {
    loadUser();
    loadChats();
    return () => {
      Object.values(pollersRef.current).forEach((cancel) => {
        if (typeof cancel === "function") cancel();
      });
      pollersRef.current = {};
    };
  }, [loadChats, loadUser]);

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  const handleSwitchUser = () => {
    localStorage.removeItem("demo_user");
    setDemoUser(null);
  };

  if (!demoUser) {
    return <UserPicker onUserSelected={setDemoUser} />;
  }

  return (
    <div className="demo-shell">
      <aside className="demo-sidebar">
        <div className="demo-brand">
          <div className="demo-brand-title">Parallel Demo</div>
          <div className="demo-brand-subtitle">Web to Extension loop</div>
        </div>

        <form className="demo-chat-form" onSubmit={handleCreateChat}>
          <input
            type="text"
            value={newChatName}
            onChange={(event) => setNewChatName(event.target.value)}
            placeholder="New chat name"
            aria-label="New chat name"
          />
          <button type="submit" disabled={creatingChat}>
            {creatingChat ? "Creating..." : "New chat"}
          </button>
        </form>

        <div className="demo-chat-list">
          {chats.length === 0 && (
            <div className="demo-muted">No chats yet. Create one to begin.</div>
          )}
          {chats.map((chat) => {
            const chatId = chat.id || chat.chat_id;
            return (
              <button
                type="button"
                key={chatId}
                className={`demo-chat-item ${chatId === selectedChatId ? "active" : ""}`}
                onClick={() => setSelectedChatId(chatId)}
              >
                <div className="demo-chat-name">{chat.name}</div>
                {chat.last_message_at && (
                  <div className="demo-chat-meta">
                    {new Date(chat.last_message_at).toLocaleString()}
                  </div>
                )}
              </button>
            );
          })}
        </div>

        {userError && <div className="demo-error">{userError}</div>}
      </aside>

      <main className="demo-main">
        <header className="demo-header">
          <div>
            <div className="demo-title">{selectedChat?.name || "Select a chat"}</div>
            <div className="demo-subtitle">
              Dispatch tasks to the VS Code extension and watch completions roll in.
            </div>
          </div>
          <div className="demo-user">
            <span className="demo-user-badge">{demoUser?.toUpperCase()}</span>
            <span className="demo-user-name">{user?.name || "Demo User"}</span>
            <button className="switch-user-btn" onClick={handleSwitchUser}>
              Switch User
            </button>
          </div>
        </header>

        <section className="demo-messages">
          {messagesLoading && <div className="demo-muted">Loading messages...</div>}
          {!messagesLoading && messages.length === 0 && (
            <div className="demo-muted">No messages yet. Dispatch your first task.</div>
          )}
          {messages.map((message) => {
            const status = message.task_id ? taskStatusById[message.task_id] : null;
            const result = message.task_id ? taskResultById[message.task_id] : null;
            return (
              <div
                key={message.id}
                className={`demo-message ${message.role === "user" ? "user" : "assistant"}`}
              >
                <div className="demo-message-text">{message.content}</div>
                {message.task_id && (
                  <div className="demo-task-status">
                    <span className={`demo-pill ${status || "pending"}`}>
                      {status || "pending"}
                    </span>
                    {result?.files_modified?.length > 0 && (
                      <span className="demo-task-files">
                        Files: {result.files_modified.join(", ")}
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </section>

        <form className="demo-input" onSubmit={handleSend}>
          <input
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Describe the change for the extension..."
            disabled={!selectedChatId || sending}
          />
          <button type="submit" disabled={!selectedChatId || sending}>
            {sending ? "Dispatching..." : "Dispatch"}
          </button>
        </form>
        {sendError && <div className="demo-error">{sendError}</div>}
      </main>
    </div>
  );
}
