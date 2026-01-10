import { useEffect, useRef, useState, useCallback } from "react";
import "./RoomDrawer.css";
import {
  getRoomDetails,
  getRoomMembers,
  listRoomChats,
  createRoomChat,
} from "../lib/tasksApi";
import { API_BASE_URL } from "../config";

export default function RoomDrawer({
  roomId,
  isOpen,
  onClose = () => {},
  onChatSelect = () => {},
  selectedChatId = null,
}) {
  const [room, setRoom] = useState(null);
  const [members, setMembers] = useState([]);
  const [chats, setChats] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false); // controls visibility of the form
  const [creating, setCreating] = useState(false); // in-flight API status
  const [newChatName, setNewChatName] = useState("");
  const [contextCollapsed, setContextCollapsed] = useState(false);
  const backdropRef = useRef(null);

  const loadAll = useCallback(async () => {
    if (!roomId) return;
    setLoading(true);
    setError("");
    try {
      const [roomData, memberList, chatList] = await Promise.all([
        getRoomDetails(roomId),
        getRoomMembers(roomId),
        listRoomChats(roomId),
      ]);
      setRoom(roomData || null);
      setMembers(memberList || []);
      setChats(chatList || []);
    } catch (err) {
      console.error("Failed to load room drawer data", err);
      setError("Could not load room details");
    } finally {
      setLoading(false);
    }
  }, [roomId]);

  useEffect(() => {
    if (!isOpen || !roomId) return;
    loadAll();
  }, [isOpen, roomId, loadAll]);

  useEffect(() => {
    if (!isOpen) return;
    const handleEsc = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [isOpen, onClose]);

  const handleBackdropClick = (e) => {
    if (e.target === backdropRef.current) {
      onClose();
    }
  };

  const handleCreateChat = async () => {
    const trimmedName = newChatName.trim();

    // console.log("🔵 [CREATE CHAT] Starting");
    // console.log("Chat name:", trimmedName);
    // console.log("Room ID:", roomId);

    if (!trimmedName) {
      setError("Chat name cannot be empty");
      return;
    }

    if (!roomId) {
      setError("No room selected");
      return;
    }

    setCreating(true);
    setError("");

    try {
      // console.log("🔷 [CREATE CHAT] Calling API");
      const chat = await createRoomChat(roomId, trimmedName);
      // console.log("✅ [CREATE CHAT] Success:", chat);

      setChats((prev) => [chat, ...prev]);

      const chatId = chat.id || chat.chat_id || chat.uuid;
      // console.log("📌 [CREATE CHAT] Chat ID:", chatId);

      if (chatId) {
        setShowForm(false);
        setNewChatName("");
        onChatSelect(chatId);
        onClose();
      } else {
        setError("Created chat but missing ID");
      }
    } catch (err) {
      console.error("❌ [CREATE CHAT] Error:", err);
      setError(`Failed: ${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div
      ref={backdropRef}
      className={`room-drawer-backdrop ${isOpen ? "open" : ""}`}
      onMouseDown={handleBackdropClick}
    >
      <aside className={`room-drawer ${isOpen ? "open" : ""}`}>
        <div className="room-drawer-header">
          <div>
            <p className="eyebrow">Room Context</p>
            <h3>{room?.name || "Room"}</h3>
          </div>
          <button className="close-btn" onClick={onClose} aria-label="Close room drawer">
            ×
          </button>
        </div>

        {loading && <div className="drawer-hint">Loading room…</div>}
        {error && (
          <div
            className="drawer-error"
            style={{
              padding: "8px",
              background: "#fee",
              border: "1px solid #c00",
              borderRadius: "4px",
              color: "#c00",
              marginTop: "8px",
            }}
          >
            ⚠️ {error}
          </div>
        )}

        {!loading && room && (
          <div className="room-context">
            <div className="room-context-head">
              <div>
                <p className="eyebrow">Room Context</p>
                <h4>{room?.name || "Room"}</h4>
              </div>
              <div className="context-actions">
                <button
                  className="chip ghost"
                  onClick={() => setContextCollapsed((v) => !v)}
                >
                  {contextCollapsed ? "Show" : "Hide"}
                </button>
                <button className="chip ghost" onClick={loadAll}>
                  Refresh
                </button>
              </div>
            </div>

            {!contextCollapsed && (
              <div className="context-body">
                <div className="context-block">
                  <p className="label">Project summary</p>
                  <p className="context-text">{room.project_summary || "No summary yet."}</p>
                </div>
                <div className="context-block">
                  <p className="label">Memory</p>
                  <p className="context-text">{room.memory_summary || "No memory yet."}</p>
                </div>
                <div className="context-block">
                  <p className="label">Members</p>
                  <div className="member-chips">
                    {members.map((m) => (
                      <span key={m.id || m.user_id} className="chip">
                        {m.name || m.email || m.user_id}
                        {m.role_in_room || m.role ? (
                          <span className="chip-role">
                            {m.role_in_room || m.role}
                          </span>
                        ) : null}
                      </span>
                    ))}
                    {members.length === 0 && (
                      <span className="context-text">No members listed.</span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="drawer-section">
          <div className="drawer-section-head">
            <h4>Chat instances</h4>
            <button
              className="chip ghost"
              onClick={() => {
                setShowForm((v) => !v);
                if (!showForm) {
                  setNewChatName("");
                  setError("");
                }
              }}
            >
              + New
            </button>
          </div>

          {showForm && (
            <div className="new-chat">
              <input
                type="text"
                value={newChatName}
                onChange={(e) => {
                  setNewChatName(e.target.value);
                }}
                placeholder="New chat name"
                autoFocus
              />
              <div style={{ display: "flex", gap: "8px" }}>
                <button
                  className="btn primary"
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    handleCreateChat();
                  }}
                  disabled={creating || !newChatName.trim()}
                  type="button"
                >
                  {creating ? "Creating..." : "Create"}
                </button>
                <button
                  className="btn ghost"
                  onClick={() => {
                    setShowForm(false);
                    setNewChatName("");
                    setError("");
                  }}
                  disabled={creating}
                  type="button"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {loading && <div className="drawer-hint">Loading chats…</div>}
          {!loading && chats.length === 0 && (
            <div className="drawer-hint">Create your first chat</div>
          )}

          <div className="chat-instance-list">
            {chats.map((chat) => {
              const chatId = chat.id || chat.chat_id || chat.uuid;
              return (
                <button
                  key={chatId}
                  className={`chat-instance ${selectedChatId === chatId ? "active" : ""}`}
                  onClick={() => {
                    onChatSelect(chatId);
                    onClose();
                  }}
                >
                  <div className="chat-instance-main">
                    <div className="chat-name">{chat.name || "Chat"}</div>
                    <div className="chat-meta">
                      <span>{chat.message_count ?? 0} msgs</span>
                      {chat.last_message_at && (
                        <span className="dot">•</span>
                      )}
                      {chat.last_message_at && (
                        <span>{new Date(chat.last_message_at).toLocaleString()}</span>
                      )}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </aside>
    </div>
  );
}
