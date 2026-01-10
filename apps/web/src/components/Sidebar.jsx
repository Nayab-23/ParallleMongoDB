import { useState } from "react";
import { NavLink } from "react-router-dom";
import { FiTerminal } from "react-icons/fi";
import ThemeToggle from "./ThemeToggle";
import logo from "../assets/parallel-logo.png";
import "./Sidebar.css";
import { API_BASE_URL } from "../config";
import { createChat, renameChat, deleteChat } from "../lib/tasksApi";
import MentionInput from "./common/MentionInput";
import SystemAgentChatItem from "./SystemAgentChatItem";
import "./SystemAgentChatItem.css";
import "./SidebarExperimental.css";

const ADMIN_EMAILS = [
  "sev777spag3@yahoo.com",
  "severin.spagnola@sjsu.edu",
  "minecraftseverin@gmail.com",
];

export default function Sidebar({
  active = "Team",
  onSelect = () => {},
  onLogout = () => {},
  onRoomClick = () => {},
  currentUser = null,
  collapsed = false,
  onCollapseToggle = () => {},
  openRoomId = null,
  chats = [], // ADD THIS
  onChatCreate = () => {},  // ADD THIS
  onChatRename = () => {},  // ADD THIS
  onChatDelete = () => {},  // ADD THIS
  chatLoadError = null,
  onChatRetry = () => {},
  experimentalChats = [],
  onExperimentalSelect = () => {},
}) {
  // Check both backend flag and hardcoded admin emails
  const isPlatformAdmin =
    currentUser?.is_platform_admin === true ||
    ADMIN_EMAILS.includes((currentUser?.email || "").toLowerCase());
  const navItems = [
    { label: "Timeline" },
    { label: "Manager" },
    { label: "VS Code", route: "/app/vscode", icon: <FiTerminal size={16} /> },
    { label: "Settings", route: "/app/settings" },
  ];

  const navLinkClass = ({ isActive }) =>
    `sidebar-btn ghost${isActive ? " active" : ""}`;

  const [creatingRoom, setCreatingRoom] = useState(false);
  const [newRoomName, setNewRoomName] = useState("");

  const handleCreateRoom = async (e) => {
    e.preventDefault();
    if (!newRoomName.trim()) return;

    try {
      const newChat = await createChat(newRoomName);
      setNewRoomName("");
      setCreatingRoom(false);
      
      // Use the new handler
      onChatCreate(newChat);  // CHANGED
    } catch (err) {
      console.error("Failed to create chat:", err);
      alert("Failed to create chat. Please try again.");
    }
  };

  return (
    <div
      className={`sidebar glass ${collapsed ? "collapsed" : ""}`}
      onMouseEnter={() => onCollapseToggle(false)}
      onMouseLeave={() => onCollapseToggle(true)}
    >
      <div className="sidebar-top">
        <div className="sidebar-header">
          <button
            className="logo-button"
            aria-label="New chat"
            onClick={() => onSelect("Chat")}
          >
            <img src={logo} alt="Parallel Logo" className="sidebar-logo" />
          </button>
        </div>

        <div className="sidebar-scroll">
        <div className="nav-list">
          {navItems.map((item) =>
            item.route ? (
              <NavLink
                key={item.label}
                to={item.route}
                className={navLinkClass}
                title={item.label}
              >
                {item.icon && <span className="nav-icon">{item.icon}</span>}
                <span className="nav-text">{item.label}</span>
              </NavLink>
            ) : (
              <button
                key={item.label}
                className={`sidebar-btn ghost ${
                  active && active === item.label ? "active" : ""
                }`}
                onClick={() => onSelect(item.label)}
                title={item.label}
              >
                {item.icon && <span className="nav-icon">{item.icon}</span>}
                <span className="nav-text">{item.label}</span>
              </button>
            )
          )}
          {isPlatformAdmin && (
            <NavLink
              to="/admin"
              className={navLinkClass}
              title="Admin"
            >
              <span className="nav-text">Admin</span>
            </NavLink>
          )}
        </div>

        <div className="chat-list">
          <div className="section-label" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Chats</span>
            <button
              className="sidebar-btn-small"
              onClick={() => setCreatingRoom(!creatingRoom)}
              title="Create new chat"
              style={{
                padding: "2px 8px",
                fontSize: "12px",
                background: "var(--color-primary)",
                color: "white",
                border: "none",
                borderRadius: "4px",
                cursor: "pointer"
              }}
            >
              +
            </button>
          </div>

          {creatingRoom && (
            <form onSubmit={handleCreateRoom} style={{ padding: "8px 0" }}>
              <MentionInput
                value={newRoomName}
                onChange={setNewRoomName}
                placeholder="Chat name..."
                className="room-input"
              />
              <div style={{ display: "flex", gap: "4px" }}>
                <button
                  type="submit"
                  style={{
                    flex: 1,
                    padding: "4px",
                    fontSize: "12px",
                    background: "var(--color-primary)",
                    color: "white",
                    border: "none",
                    borderRadius: "4px",
                    cursor: "pointer"
                  }}
                >
                  Create
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCreatingRoom(false);
                    setNewRoomName("");
                  }}
                  style={{
                    flex: 1,
                    padding: "4px",
                    fontSize: "12px",
                    background: "var(--color-surface)",
                    border: "1px solid var(--color-border)",
                    borderRadius: "4px",
                    cursor: "pointer"
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
          {!creatingRoom && (
            <div style={{ padding: "4px 0 8px 0" }}>
              <button
                className="sidebar-btn"
                style={{ width: "100%", justifyContent: "center" }}
                onClick={() => setCreatingRoom(true)}
              >
                + New Chat
              </button>
            </div>
          )}

          {chatLoadError && (
            <div className="error-state" style={{ marginBottom: 8, padding: 8 }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>Chats failed to load</div>
              <div style={{ fontSize: 12 }}>{chatLoadError.message || "Unknown error"}</div>
              {chatLoadError.request_id && <div className="error-meta">request_id: {chatLoadError.request_id}</div>}
              <button className="sidebar-btn" style={{ marginTop: 6, fontSize: 12 }} onClick={onChatRetry}>
                Retry
              </button>
            </div>
          )}

          <div className="chat-items">
            {/* Remove loading state - Dashboard handles it */}
          {chats.length === 0 && (
            <div style={{ padding: "8px", fontSize: "13px", opacity: 0.6 }}>
              No chats yet. Create one!
            </div>
          )}
          {chats.length > 0 && (
            <>
              {console.log("🎨 [Sidebar] Rendering chats:", chats.length, chats.map((c) => c?.id || c?.chat_id))}
            </>
          )}

          {chats.map((chat) => {
            const isSystemAgent = chat.type === "system_agent" || chat.is_system;
            if (isSystemAgent) {
              if (!isPlatformAdmin) return null;
              return <SystemAgentChatItem key={chat.id || chat.chat_id} chat={chat} />;
            }
            return (
              <button
                key={chat.id || chat.chat_id}
                className={`chat-item ${openRoomId === (chat.id || chat.chat_id) ? "active" : ""}`}
                type="button"
                onClick={() => {
                  onRoomClick({
                    id: chat.id || chat.chat_id,
                    name: chat.name || "Chat",
                    room_id: chat.room_id,
                    last_message_at: chat.last_message_at,
                    unread_count: chat.unread_count,
                  });
                }}
              >
                <div style={{ display: "flex", alignItems: "center", width: "100%", gap: 6 }}>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
                    <span className="chat-title">{chat.name || "Chat"}</span>
                    {chat.last_message_at && (
                      <span style={{ fontSize: "11px", opacity: 0.6 }}>
                        {new Date(chat.last_message_at).toLocaleString()}
                      </span>
                    )}
                  </div>
                  <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                    {chat.unread_count > 0 && (
                      <span style={{ fontSize: "11px", opacity: 0.8 }}>{chat.unread_count}</span>
                    )}
                    <button
                      type="button"
                      title="Rename chat"
                      className="sidebar-btn-small"
                      onClick={(e) => {
                        e.stopPropagation();
                        const name = prompt("Rename chat", chat.name || "Chat");
                        if (name && name.trim()) {
                          renameChat(chat.id || chat.chat_id, name.trim())
                            .then(() => {
                              onChatRename(chat.id || chat.chat_id, name.trim());  // CHANGED
                            })
                            .catch(() => alert("Rename failed"));
                        }
                      }}
                    >
                      ✏️
                    </button>
                    <button
                      type="button"
                      title="Delete chat"
                      className="sidebar-btn-small"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (!window.confirm("Delete this chat?")) return;
                        deleteChat(chat.id || chat.chat_id)
                          .then(() => {
                            onChatDelete(chat.id || chat.chat_id);  // CHANGED
                          })
                          .catch(() => alert("Delete failed"));
                      }}
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {Array.isArray(experimentalChats) && experimentalChats.length > 0 && isPlatformAdmin && (
          <div className="chat-items" style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--color-border)" }}>
            <div className="section-label" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>Experimental</span>
            </div>
            {experimentalChats.map((exp) => (
              <button
                key={exp.id || exp.chat_id || exp.name}
                className="chat-item experimental"
                type="button"
                onClick={() => onExperimentalSelect(exp)}
                title={exp.name || "Experimental"}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6, width: "100%" }}>
                  <span className="chat-title">{exp.name || "Experimental"}</span>
                  <span style={{ marginLeft: "auto", fontSize: "11px", opacity: 0.7 }}>Graph</span>
                </div>
              </button>
            ))}
          </div>
        )}
        </div>
      </div>
      </div>

      <div className="sidebar-bottom">
        <ThemeToggle collapsed={collapsed} />
        <button className="sidebar-btn ghost" onClick={onLogout} title="Logout">
          <span role="img" aria-label="logout">🚪</span>
          <span className="nav-text">Logout</span>
        </button>
      </div>

    </div>
  );
}
