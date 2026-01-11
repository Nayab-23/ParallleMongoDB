import { useCallback, useEffect, useState } from "react";
import "./NewDemoChat.css";
import UserPicker from "./UserPicker";
import VscodePage from "./VscodePage";
import {
  createChat,
  dispatchChat,
  getChatMessages,
  getTaskStatus,
  listChats,
  sendSiteMessage,
} from "../api/demoApi";

const POLL_INTERVAL_MS = 2000;
const POLL_MAX_ATTEMPTS = 60;

export default function NewDemoChat() {
  const [demoUser, setDemoUser] = useState(() => localStorage.getItem("demo_user"));
  const [chats, setChats] = useState([]);
  const [selectedChatId, setSelectedChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [activeTab, setActiveTab] = useState("timeline");
  const [mode, setMode] = useState("site"); // site | agent | patch
  const [theme, setTheme] = useState("dark");
  const [chatStyle, setChatStyle] = useState("classic"); // classic | glass | minimal
  const [taskStatuses, setTaskStatuses] = useState({});

  const loadChats = useCallback(async () => {
    try {
      const data = await listChats({ limit: 100 });
      const items = Array.isArray(data?.items) ? data.items : [];
      setChats(items);
      if (!selectedChatId && items.length > 0) {
        setSelectedChatId(items[0].chat_id || items[0].id);
      }
    } catch (err) {
      console.error("Failed to load chats:", err);
    }
  }, [selectedChatId]);

  const loadMessages = useCallback(async () => {
    if (!selectedChatId) {
      setMessages([]);
      return;
    }
    try {
      const data = await getChatMessages(selectedChatId);
      setMessages(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error("Failed to load messages:", err);
      setMessages([]);
    }
  }, [selectedChatId]);

  const pollTaskStatus = useCallback((taskId) => {
    let attempts = 0;
    const poll = async () => {
      while (attempts < POLL_MAX_ATTEMPTS) {
        try {
          const data = await getTaskStatus(taskId);
          setTaskStatuses((prev) => ({ ...prev, [taskId]: data.status }));
          if (data.status === "done" || data.status === "error") {
            break;
          }
        } catch (err) {
          if (err?.status === 404) break;
        }
        attempts++;
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      }
    };
    poll();
  }, []);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;

    setSending(true);
    setInput("");

    // If no chat selected, create one
    let chatId = selectedChatId;
    if (!chatId) {
      try {
        const newChat = await createChat(`Chat ${new Date().toLocaleTimeString()}`);
        chatId = newChat.chat_id || newChat.id;
        setChats((prev) => [newChat, ...prev]);
        setSelectedChatId(chatId);
      } catch (err) {
        console.error("Failed to create chat:", err);
        setSending(false);
        return;
      }
    }

    // Add user message to UI immediately
    const tempMessage = {
      id: `temp-${Date.now()}`,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempMessage]);

    try {
      if (mode === "agent") {
        // Dispatch to extension
        const response = await dispatchChat(chatId, text);
        const taskId = response.task_id;
        if (taskId) {
          setTaskStatuses((prev) => ({ ...prev, [taskId]: "pending" }));
          setMessages((prev) => [
            ...prev,
            {
              id: `task-${taskId}`,
              role: "assistant",
              content: "Task sent to VS Code extension.",
              task_id: taskId,
              created_at: new Date().toISOString(),
            },
          ]);
          pollTaskStatus(taskId);
        }
      } else {
        // Site mode - call real LLM endpoint
        const response = await sendSiteMessage(chatId, text);
        setMessages((prev) => [
          ...prev,
          {
            id: response.assistant_message_id,
            role: "assistant",
            content: response.reply,
            created_at: response.created_at,
          },
        ]);
      }
      await loadChats();
    } catch (err) {
      console.error("Failed to send message:", err);
      // Show error message to user
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: `Error: ${err.message || "Failed to get response from AI"}`,
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  const handleNewChat = async () => {
    try {
      const newChat = await createChat(`New Chat ${new Date().toLocaleTimeString()}`);
      setChats((prev) => [newChat, ...prev]);
      setSelectedChatId(newChat.chat_id || newChat.id);
      setMessages([]);
    } catch (err) {
      console.error("Failed to create chat:", err);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("demo_user");
    setDemoUser(null);
  };

  useEffect(() => {
    if (demoUser) {
      loadChats();
    }
  }, [demoUser, loadChats]);

  useEffect(() => {
    if (selectedChatId) {
      loadMessages();
    }
  }, [selectedChatId, loadMessages]);

  if (!demoUser) {
    return <UserPicker onUserSelected={setDemoUser} />;
  }

  return (
    <div className={`demo-app theme-${theme}`}>
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h2>Parallel</h2>
          <span className="demo-badge">{demoUser.toUpperCase()}</span>
        </div>

        {/* Tabs */}
        <nav className="tabs">
          <button
            className={activeTab === "timeline" ? "active" : ""}
            onClick={() => setActiveTab("timeline")}
          >
            Timeline
          </button>
          <button
            className={activeTab === "manager" ? "active" : ""}
            onClick={() => setActiveTab("manager")}
          >
            Manager
          </button>
          <button
            className={activeTab === "vscode" ? "active" : ""}
            onClick={() => setActiveTab("vscode")}
          >
            VS Code
          </button>
          <button
            className={activeTab === "settings" ? "active" : ""}
            onClick={() => setActiveTab("settings")}
          >
            Settings
          </button>
        </nav>

        {/* Chats Section */}
        <div className="chats-section">
          <div className="chats-header">
            <h3>Chats</h3>
            <button className="new-chat-btn" onClick={handleNewChat}>
              + New Chat
            </button>
          </div>
          <div className="chats-list">
            {chats.map((chat) => (
              <div
                key={chat.id || chat.chat_id}
                className={`chat-item ${
                  (chat.id || chat.chat_id) === selectedChatId ? "active" : ""
                }`}
                onClick={() => setSelectedChatId(chat.id || chat.chat_id)}
              >
                <div className="chat-name">{chat.name}</div>
                <div className="chat-time">
                  {chat.last_message_at
                    ? new Date(chat.last_message_at).toLocaleTimeString()
                    : ""}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="sidebar-footer">
          <button className="theme-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? "🌙" : "☀️"} {theme === "dark" ? "Dark" : "Light"}
          </button>
          <button className="logout-btn" onClick={handleLogout}>
            Logout
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-content">
        {/* Show VS Code page when that tab is active */}
        {activeTab === "vscode" ? (
          <div style={{ padding: "24px", overflow: "auto", height: "100%" }}>
            <VscodePage user={{ name: demoUser }} />
          </div>
        ) : activeTab === "timeline" || activeTab === "manager" || activeTab === "settings" ? (
          // Show chat interface for timeline, manager, and settings tabs (for now)
          <>
            {/* Chat Header */}
            <div className="chat-header">
              <div className="style-selector">
                <button
                  className={chatStyle === "classic" ? "active" : ""}
                  onClick={() => setChatStyle("classic")}
                >
                  Classic
                </button>
                <button
                  className={chatStyle === "glass" ? "active" : ""}
                  onClick={() => setChatStyle("glass")}
                >
                  Glass
                </button>
                <button
                  className={chatStyle === "minimal" ? "active" : ""}
                  onClick={() => setChatStyle("minimal")}
                >
                  Minimal
                </button>
              </div>
            </div>

            {/* Messages */}
            <div className={`messages-container style-${chatStyle}`}>
              {messages.map((msg) => (
                <div
                  key={msg.id || msg.message_id}
                  className={`message ${msg.role}`}
                >
                  <div className="message-bubble">
                    {msg.content}
                    {msg.task_id && (
                      <div className="task-status">
                        Status: {taskStatuses[msg.task_id] || "pending"}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Input Area */}
            <div className="input-area">
              <div className="mode-tabs">
                <button
                  className={mode === "site" ? "active" : ""}
                  onClick={() => setMode("site")}
                >
                  Site
                </button>
                <button
                  className={mode === "agent" ? "active" : ""}
                  onClick={() => setMode("agent")}
                >
                  Agent (VS Code)
                </button>
                <button
                  className={mode === "patch" ? "active" : ""}
                  onClick={() => setMode("patch")}
                >
                  Patch
                </button>
              </div>

              <div className="input-controls">
                <label>
                  <input type="checkbox" /> Include context preview
                </label>
                <label>
                  <input type="checkbox" /> Diagnostics mode
                </label>
              </div>

              <div className="input-row">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={(e) => e.key === "Enter" && handleSend()}
                  placeholder={`Send message in ${mode} mode...`}
                  disabled={sending}
                />
                <button onClick={handleSend} disabled={sending || !input.trim()}>
                  {sending ? "Sending..." : "Send"}
                </button>
              </div>
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
