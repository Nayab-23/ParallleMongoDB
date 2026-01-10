import { useEffect, useState } from "react";
import { AnimatePresence, motion as Motion } from "framer-motion";
import "./Manager.css";

import {
  fetchTeam,
  listRooms,
  getUserRooms,
  updateUserRooms,
  createRoom,
  deleteRoom,
} from "../lib/tasksApi";
import OrgIntelligenceGraph from "../components/brief/OrgIntelligenceGraph";

const tabs = [
  { id: "team", label: "Team" },
  { id: "rooms", label: "Rooms" },
  { id: "org", label: "Organization" },
];

export default function Manager({ currentUser }) {
  const [team, setTeam] = useState([]);
  const [rooms, setRooms] = useState([]);
  const [memberships, setMemberships] = useState({}); // userId -> [roomIds]
  const [permissions, setPermissions] = useState({}); // UI-only toggles

  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("");
  const [membershipStatus, setMembershipStatus] = useState("");
  const [savingUser, setSavingUser] = useState({});
  const [activeTab, setActiveTab] = useState("team");
  const [newRoomName, setNewRoomName] = useState("");
  const [roomStatus, setRoomStatus] = useState("");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setStatus("");
      try {
        const [membersRes, roomsRes] = await Promise.all([
          fetchTeam(),
          listRooms(),
        ]);

        const members = membersRes || [];
        setTeam(members);
        setRooms(roomsRes || []);

        // seed permissions toggle UI defaults (manager only)
        setPermissions((prev) => {
          const next = { ...prev };
          for (const m of members) {
            const manager = m.permissions?.backend ?? false;
            next[m.id] = { manager };
          }
          return next;
        });

        // fetch memberships per user
        const pairs = await Promise.all(
          members.map(async (m) => {
            try {
              const ids = await getUserRooms(m.id);
              return [m.id, ids];
            } catch (err) {
              console.error("Failed to load rooms for user", m.id, err);
              return [m.id, []];
            }
          })
        );
        setMemberships(Object.fromEntries(pairs));
      } catch (err) {
        console.error("Manager load failed", err);
        setStatus("Failed to load team or rooms.");
      } finally {
        setLoading(false);
      }
    };

    load();
  }, []);

  const toggleManagerAccess = async (userId, current) => {
    setStatus("");
    setSavingUser((prev) => ({ ...prev, [userId]: true }));
    try {
      const res = await fetch(`/api/users/${userId}/manager`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ manager: !current }),
      });
      if (!res.ok) {
        throw new Error("Failed to update manager access");
      }
      const data = await res.json().catch(() => ({}));
      setPermissions((prev) => ({
        ...prev,
        [userId]: { manager: data?.manager ?? !current },
      }));
    } catch (err) {
      console.error("Failed to update manager access", err);
      setStatus(err?.message || "Unable to update manager access right now.");
    } finally {
      setSavingUser((prev) => {
        const next = { ...prev };
        delete next[userId];
        return next;
      });
    }
  };

  const toggleRoomMembership = async (userId, roomId, checked) => {
    setMembershipStatus("");
    const prevRooms = memberships[userId] || [];
    const nextRooms = checked
      ? Array.from(new Set([...prevRooms, roomId]))
      : prevRooms.filter((id) => id !== roomId);

    if (nextRooms.length === 0) {
      setMembershipStatus("Each user must belong to at least one room.");
      return;
    }

    setMemberships((prev) => ({ ...prev, [userId]: nextRooms }));
    setSavingUser((prev) => ({ ...prev, [userId]: true }));

    try {
      await updateUserRooms(userId, nextRooms);
    } catch (err) {
      console.error("Room membership update failed", err);
      setMembershipStatus(
        err?.message || "Could not update room membership right now."
      );
      // revert
      setMemberships((prev) => ({ ...prev, [userId]: prevRooms }));
    } finally {
      setSavingUser((prev) => {
        const next = { ...prev };
        delete next[userId];
        return next;
      });
    }
  };

  if (!currentUser) {
    return (
      <div className="manager-shell">
        <div className="manager-panel">Loading user…</div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="manager-shell">
        <div className="manager-panel">Loading manager data…</div>
      </div>
    );
  }

  return (
    <div className="manager-shell">
      <div className="manager-top">
        <div>
          <p className="eyebrow">Org control</p>
          <h2>Workspace Manager</h2>
          <p className="subhead">
            Manage user permissions and room memberships.
          </p>
        </div>
        {status && <div className="status-pill error">{status}</div>}
      </div>

      <div className="manager-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={tab.id === activeTab ? "manager-tab active" : "manager-tab"}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {activeTab === "team" && (
          <Motion.div
            key="team"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="manager-panel"
          >
            <div className="panel-header">
              <div>
                <h3>Team</h3>
                <p className="subhead">
                  Toggle platform access and update roles.
                </p>
              </div>
            </div>
            <div className="manager-list">
              {team.length === 0 && <div>No teammates yet.</div>}
              {team.map((m) => (
                <div key={m.id} className="member">
                  <div className="member-main">
                    <div className="member-title">{m.name}</div>
                    <div className="roles">{m.email}</div>
                    <div className="member-controls">
                      <div className="perm-row">
                        <label>
                          <input
                            type="checkbox"
                            checked={
                              permissions[m.id]?.manager ??
                              m.permissions?.backend ??
                              false
                            }
                            onChange={() =>
                              toggleManagerAccess(
                                m.id,
                                permissions[m.id]?.manager ??
                                  m.permissions?.backend ??
                                  false
                              )
                            }
                            disabled={!!savingUser[m.id]}
                          />
                          Manager Access
                        </label>
                      </div>
                    </div>
                  </div>
                  <div className="roles">{m.status || "active"}</div>
                </div>
              ))}
        </div>
      </Motion.div>
    )}

    {activeTab === "rooms" && (
  <Motion.div
            key="rooms"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="manager-panel"
          >
        <div className="panel-header">
          <div>
            <h3>Rooms</h3>
            <p className="subhead">
              Add or remove people from rooms (matrix view).
            </p>
          </div>
          {membershipStatus && (
            <div className="status-pill error">{membershipStatus}</div>
          )}
        </div>

        <div className="room-actions">
          <input
            className="auth-input"
            placeholder="New room name"
            value={newRoomName}
            onChange={(e) => setNewRoomName(e.target.value)}
            style={{ maxWidth: 260 }}
          />
          <button
            className="btn"
            onClick={async () => {
              const name = newRoomName.trim();
              if (!name) return;
              setRoomStatus("");
              try {
                const created = await createRoom(name);
                const normalized = {
                  id: created.id || created.room_id,
                  name: created.name || created.room_name || name,
                  member_count: 0,
                };
                setRooms((prev) => [normalized, ...prev]);
                setNewRoomName("");
                setRoomStatus("Room created.");
              } catch (err) {
                console.error("Create room failed", err);
                setRoomStatus("Could not create room.");
              }
            }}
          >
            Create room
          </button>
          {roomStatus && <div className="roles">{roomStatus}</div>}
        </div>

        <div className="rooms-matrix">
          <div className="matrix-header">
            <div className="matrix-user-col">User</div>
            <div className="matrix-rooms">
              {rooms.map((room) => (
                <div key={room.id} className="matrix-room">
                  <div className="room-name">
                    {room.name}
                    <button
                      className="btn"
                      style={{ padding: "2px 6px", marginLeft: 6 }}
                      onClick={async () => {
                        if (!window.confirm("Delete this room?")) return;
                        try {
                          await deleteRoom(room.id);
                          setRooms((prev) =>
                            prev.filter((r) => r.id !== room.id)
                          );
                          setMemberships((prev) => {
                            const next = {};
                            for (const [uid, list] of Object.entries(prev)) {
                              next[uid] = (list || []).filter(
                                (rid) => rid !== room.id
                              );
                            }
                            return next;
                          });
                        } catch (err) {
                          console.error("Delete room failed", err);
                          setRoomStatus("Could not delete room.");
                        }
                      }}
                      title="Delete room"
                    >
                      ×
                    </button>
                  </div>
                  <div className="roles">
                    {room.member_count
                      ? `${room.member_count} members`
                      : "Room"}
                  </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="matrix-body">
                {team.map((user) => {
                  const userRoomIds = memberships[user.id] || [];
                  const saving = !!savingUser[user.id];
                  return (
                    <div key={user.id} className="matrix-row">
                      <div className="matrix-user">
                        <div className="member-title">
                          {user.name || user.email}
                        </div>
                        <div className="roles">{user.email}</div>
                      </div>
                      <div className="matrix-rooms">
                        {rooms.map((room) => {
                          const checked = userRoomIds.includes(room.id);
                          return (
                            <label key={room.id} className="matrix-check">
                              <input
                                type="checkbox"
                                checked={checked}
                                disabled={saving}
                                onChange={(e) =>
                                  toggleRoomMembership(
                                    user.id,
                                    room.id,
                                    e.target.checked
                                  )
                                }
                              />
                            </label>
                          );
                        })}
                      </div>
                      {saving && <span className="roles saving">Saving…</span>}
                    </div>
                  );
                })}
          </div>
        </div>
      </Motion.div>
    )}

    {activeTab === "org" && <OrgIntelligenceGraph />}

      </AnimatePresence>
    </div>
  );
}
