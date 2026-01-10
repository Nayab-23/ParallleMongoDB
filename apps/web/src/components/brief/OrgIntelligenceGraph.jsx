import { useMemo, useRef, useState, useEffect, useCallback } from "react";
import { ReactFlow, Background, Controls, MiniMap, MarkerType } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./OrgIntelligenceGraph.css";
import { API_BASE_URL } from "../../config";
import { getOrgGraphData } from "../../lib/tasksApi";

const STATUS_ORDER = ["all", "healthy", "strained", "critical"];

function RoomNode({ data }) {
  const statusClass = data.status.toLowerCase();
  const chips = [];
  if (data.showFires && data.fires > 0) chips.push(`🔥 ${data.fires} fires`);
  if (data.showOverdue && data.overdue > 0) chips.push(`⏰ ${data.overdue} overdue`);
  if (data.showSentiment) chips.push(`${data.sentiment} sentiment`);
  if (data.showLastActive) chips.push(`Last active ${data.lastActive}`);

  return (
    <div className={`org-node ${statusClass}`}>
      <div className="org-node-header">
        <span className="org-node-title">{data.name}</span>
        <span className={`org-node-status ${statusClass}`}>{data.status}</span>
      </div>
      <div className="org-node-chips">
        {chips.map((chip, i) => (
          <span key={i} className="org-chip">
            {chip}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function OrgIntelligenceGraph() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [timeWindow, setTimeWindow] = useState("7d");
  const [showFires, setShowFires] = useState(true);
  const [showOverdue, setShowOverdue] = useState(true);
  const [showSentiment, setShowSentiment] = useState(true);
  const [showLastActive, setShowLastActive] = useState(true);
  const [selectedRoomId, setSelectedRoomId] = useState(null);
  const [hoveredRoom, setHoveredRoom] = useState(null);
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 });
  const [rfInstance, setRfInstance] = useState(null);
  const canvasRef = useRef(null);
  const [workspaceId, setWorkspaceId] = useState(null);
  const [allMembers, setAllMembers] = useState([]);
  const [selectedRoomForEdit, setSelectedRoomForEdit] = useState(null);
  const [addingMember, setAddingMember] = useState(false);
  const [removingMember, setRemovingMember] = useState(false);
  const [roomDetails, setRoomDetails] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [showCreateRoom, setShowCreateRoom] = useState(false);
  const [newRoomName, setNewRoomName] = useState("");
  const [creatingRoom, setCreatingRoom] = useState(false);
  const [deletingRoom, setDeletingRoom] = useState(false);
  const [sidebarExpanded, setSidebarExpanded] = useState(false);

  // API data state
  const [graphData, setGraphData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Component lifecycle logging
  useEffect(() => {
    console.log('[OrgGraph] 🚀 Component mounted');
    return () => console.log('[OrgGraph] 💀 Component unmounted');
  }, []);

  // State change logging
  useEffect(() => {
    console.log('[OrgGraph] 📊 State update:', {
      loading,
      error,
      hasGraphData: !!graphData,
      workspaceId,
      roomCount: graphData?.rooms?.length || 0
    });
  }, [loading, error, graphData, workspaceId]);

  // Fetch user's workspace list and select first available
  useEffect(() => {
    let cancelled = false;
    const loadWorkspace = async () => {
      try {
        console.log('[OrgGraph] 🔍 Fetching user workspaces from:', `${API_BASE_URL}/api/v1/workspaces`);
        const startTime = Date.now();

        const res = await fetch(`${API_BASE_URL}/api/v1/workspaces`, {
          credentials: "include",
        });

        const elapsed = Date.now() - startTime;
        console.log(`[OrgGraph] ⏱️ Workspaces response in ${elapsed}ms with status:`, res.status);

        if (!res.ok) {
          const text = await res.text().catch(() => "");
          console.error('[OrgGraph] ❌ Workspaces fetch failed:', res.status, text);
          throw new Error(`Workspace fetch failed (${res.status}): ${text}`);
        }
        const workspaces = await res.json();
        console.log('[OrgGraph] 📦 Received workspaces:', workspaces);
        console.log('[OrgGraph] Workspace count:', Array.isArray(workspaces) ? workspaces.length : 'not an array');

        if (!cancelled) {
          if (Array.isArray(workspaces) && workspaces.length > 0) {
            console.log('[OrgGraph] ✅ Using first workspace:', workspaces[0]);
            setWorkspaceId(workspaces[0].id);
          } else {
            console.warn('[OrgGraph] ⚠️ No workspaces available in response');
            setError("No workspaces available");
            setLoading(false);
          }
        }
      } catch (err) {
        if (!cancelled) {
          console.error("[OrgGraph] 💥 Failed to fetch workspace:", err);
          console.error("[OrgGraph] Error details:", {
            message: err.message,
            stack: err.stack
          });
          setError(err.message || "Failed to load workspace");
          setLoading(false);
        }
      }
    };
    loadWorkspace();
    return () => {
      cancelled = true;
    };
  }, []);

  // Fetch all organization members
  useEffect(() => {
    async function fetchMembers() {
      try {
        console.log("[OrgGraph] 👥 Fetching all org members...");
        const response = await fetch(`${API_BASE_URL}/api/v1/users`, {
          credentials: "include",
        });

        if (!response.ok) {
          console.error("[OrgGraph] Failed to fetch members:", response.status);
          return;
        }

        const users = await response.json();
        console.log("[OrgGraph] Received members:", users);

        if (!Array.isArray(users)) {
          console.error("[OrgGraph] ❌ Users response is not an array:", users);
          setAllMembers([]);
          return;
        }

        console.log("[OrgGraph] Received members:", users.length);
        setAllMembers(users);
      } catch (err) {
        console.error("[OrgGraph] Error fetching members:", err);
      }
    }

    fetchMembers();
  }, []);

  // Fetch organization graph data
  const fetchOrgData = useCallback(async () => {
    console.log('[OrgGraph] 🎯 fetchOrgData called');
    console.log('[OrgGraph] Current workspaceId:', workspaceId);

    if (!workspaceId) {
      console.log("[OrgGraph] ⏸️ No workspace ID yet, waiting...");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      console.log('[OrgGraph] 📡 Calling getOrgGraphData with workspace:', workspaceId);
      const startTime = Date.now();

      const data = await getOrgGraphData(workspaceId);

      const elapsed = Date.now() - startTime;
      console.log(`[OrgGraph] ⏱️ getOrgGraphData completed in ${elapsed}ms`);
      console.log('[OrgGraph] 📊 Received org graph data:', {
        rooms: data?.rooms?.length || 0,
        edges: data?.edges?.length || 0,
        members: Object.keys(data?.members || {}).length,
        rawData: data
      });

      setGraphData(data);
      setLoading(false);
      console.log('[OrgGraph] ✅ Org graph loaded successfully');
    } catch (err) {
      console.error("[OrgGraph] 💥 Failed to fetch org data:", err);
      console.error("[OrgGraph] Error details:", {
        message: err.message,
        stack: err.stack
      });
      setError(err.message);
      setLoading(false);
    }
  }, [workspaceId]);

  // Fetch when workspace available and auto-refresh (reduced frequency)
  useEffect(() => {
    console.log('[OrgGraph] 🔄 fetchOrgData effect triggered');
    console.log('[OrgGraph] workspaceId state:', workspaceId);

    if (!workspaceId) {
      console.log('[OrgGraph] Skipping fetchOrgData (no workspace ID)');
      return;
    }

    console.log('[OrgGraph] Calling fetchOrgData...');
    fetchOrgData();

    console.log('[OrgGraph] Setting up 60s refresh interval');
    const interval = setInterval(() => {
      console.log('[OrgGraph] 🔁 Auto-refresh triggered');
      fetchOrgData();
    }, 60000);

    return () => {
      console.log('[OrgGraph] Clearing refresh interval');
      clearInterval(interval);
    };
  }, [fetchOrgData, workspaceId]);

  // Add member to room
  async function addMemberToRoom(userId, roomId) {
    try {
      setAddingMember(true);
      console.log("[OrgGraph] Adding member", userId, "to room", roomId);

      const response = await fetch(`${API_BASE_URL}/api/v1/workspaces/${roomId}/members`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          user_id: userId,
          role: "member",
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Failed to add member: ${errorText}`);
      }

      console.log("[OrgGraph] ✅ Member added successfully");
      await fetchOrgData();
    } catch (err) {
      console.error("[OrgGraph] Error adding member:", err);
      alert(`Failed to add member: ${err.message}`);
    } finally {
      setAddingMember(false);
    }
  }

  // Remove member from room
  async function removeMemberFromRoom(userId, roomId) {
    try {
      setRemovingMember(true);
      console.log("[OrgGraph] Removing member", userId, "from room", roomId);

      const confirmed = window.confirm("Remove this member from the room?");
      if (!confirmed) {
        setRemovingMember(false);
        return;
      }

      const response = await fetch(`${API_BASE_URL}/api/v1/workspaces/${roomId}/members/${userId}`, {
        method: "DELETE",
        credentials: "include",
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Failed to remove member: ${errorText}`);
      }

      console.log("[OrgGraph] ✅ Member removed successfully");
      await fetchOrgData();
    } catch (err) {
      console.error("[OrgGraph] Error removing member:", err);
      alert(`Failed to remove member: ${err.message}`);
    } finally {
      setRemovingMember(false);
    }
  }

  // Get member details from ID
  function getMemberDetails(memberId) {
    if (!graphData?.members) return allMembers.find((m) => m.id === memberId) || null;
    return graphData.members[memberId] || allMembers.find((m) => m.id === memberId) || null;
  }

  // Get rooms a member belongs to
  function getMemberRooms(memberId) {
    if (!graphData?.rooms) return [];
    return graphData.rooms.filter((room) => room.member_ids?.includes(memberId));
  }

  // Create new room
  async function createNewRoom() {
    if (!newRoomName.trim()) {
      alert("Please enter a room name");
      return;
    }

    try {
      setCreatingRoom(true);
      console.log("[OrgGraph] 🏗️ Creating new room:", newRoomName);

      const response = await fetch(`${API_BASE_URL}/api/v1/workspaces`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: newRoomName }),
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`Failed to create room: ${error}`);
      }

      const newRoom = await response.json();
      console.log("[OrgGraph] ✅ Room created:", newRoom);

      setNewRoomName("");
      setShowCreateRoom(false);

      await fetchOrgData();

      alert(`Room "${newRoomName}" created successfully!`);
    } catch (err) {
      console.error("[OrgGraph] Error creating room:", err);
      alert(`Failed to create room: ${err.message}`);
    } finally {
      setCreatingRoom(false);
    }
  }

  // Delete room
  async function deleteRoom(roomId, roomName) {
    try {
      setDeletingRoom(true);
      console.log("[OrgGraph] 🗑️ Attempting to delete room:", roomId);

      const confirmed = window.confirm(
        `⚠️ DANGER: DELETE ROOM "${roomName}"?\n\n` +
          `This will:\n` +
          `• Remove ALL members from this room\n` +
          `• Delete ALL messages and data\n` +
          `• Cannot be undone\n\n` +
          `Type the room name to confirm deletion.`
      );

      if (!confirmed) {
        setDeletingRoom(false);
        return;
      }

      const nameConfirm = window.prompt(`Type "${roomName}" exactly to confirm deletion:`);
      if (nameConfirm !== roomName) {
        alert("Room name did not match. Deletion cancelled.");
        setDeletingRoom(false);
        return;
      }

      const response = await fetch(`${API_BASE_URL}/api/v1/workspaces/${roomId}`, {
        method: "DELETE",
        credentials: "include",
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(`Failed to delete room: ${error}`);
      }

      console.log("[OrgGraph] ⚠️ Room deleted:", roomId);

      if (selectedRoomId === roomId) {
        setSelectedRoomId(null);
        setSelectedRoomForEdit(null);
        setRoomDetails(null);
      }

      await fetchOrgData();

      alert(`Room "${roomName}" has been deleted.`);
    } catch (err) {
      console.error("[OrgGraph] Error deleting room:", err);
      alert(`Failed to delete room: ${err.message}`);
    } finally {
      setDeletingRoom(false);
    }
  }

  // Fetch room details
  async function fetchRoomDetails(roomId) {
    try {
      setLoadingDetails(true);
      console.log("[OrgGraph] 📋 Fetching room details for:", roomId);

      const response = await fetch(`${API_BASE_URL}/api/v1/workspaces/${roomId}/details`, {
        credentials: "include",
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch room details: ${response.status}`);
      }

      const details = await response.json();
      console.log("[OrgGraph] 📊 Room details received:", details);
      setRoomDetails(details);
    } catch (err) {
      console.error("[OrgGraph] Error fetching room details:", err);
      setRoomDetails(null);
    } finally {
      setLoadingDetails(false);
    }
  }

  // Process rooms with position calculation
  const processedRooms = useMemo(() => {
    if (!graphData?.rooms) return [];
    
    return graphData.rooms.map((room, index) => {
      // Calculate status from health metrics
      const status = room.health_metrics?.conflicts > 5 ? "critical" :
                     room.health_metrics?.conflicts > 2 ? "strained" : "healthy";
      
      // Format last active time
      const lastActive = room.activity_stats?.active_members_7d > 0 ? 
                        "recently" : "inactive";
      
      return {
        id: String(room.id),
        name: room.name,
        status: status,
        fires: room.health_metrics?.conflicts || 0,
        overdue: room.health_metrics?.overdue_tasks || 0,
        sentiment: room.health_metrics?.avg_sentiment?.toFixed(1) || "neutral",
        lastActive: lastActive,
        memberCount: room.member_count,
        memberIds: room.member_ids || [],
        position: { x: (index % 3) * 300 + 100, y: Math.floor(index / 3) * 200 + 100 }
      };
    });
  }, [graphData]);

  const roomById = useMemo(
    () => new Map(processedRooms.map((room) => [room.id, room])),
    [processedRooms]
  );

  // Filter rooms by search and status
  const filteredRooms = useMemo(() => {
    const query = search.trim().toLowerCase();
    return processedRooms.filter((room) => {
      const matchesSearch = query ? room.name.toLowerCase().includes(query) : true;
      const matchesStatus =
        statusFilter === "all" || room.status.toLowerCase() === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [search, statusFilter, processedRooms]);

  // Create ReactFlow nodes
  const nodes = useMemo(() => {
    return filteredRooms.map((room) => ({
      id: room.id,
      type: "roomNode",
      position: room.position,
      data: {
        ...room,
        showFires,
        showOverdue,
        showSentiment,
        showLastActive,
      },
    }));
  }, [filteredRooms, showFires, showOverdue, showSentiment, showLastActive]);

  // Create ReactFlow edges from backend data
  const edges = useMemo(() => {
    if (!graphData?.edges) return [];
    
    const visibleIds = new Set(nodes.map((node) => node.id));
    
    return graphData.edges
      .filter(edge => 
        visibleIds.has(String(edge.source_room_id)) && 
        visibleIds.has(String(edge.target_room_id))
      )
      .map((edge, index) => ({
        id: `edge-${index}`,
        source: String(edge.source_room_id),
        target: String(edge.target_room_id),
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: "#94a3b8",
        },
        style: {
          stroke: "#94a3b8",
          strokeWidth: Math.max(1, (edge.interaction_strength || 0) * 3),
        },
        label: `${edge.overlap_count} shared`,
      }));
  }, [graphData, nodes]);

  const nodeTypes = useMemo(() => ({ roomNode: RoomNode }), []);

  const selectedRoom = selectedRoomId ? roomById.get(selectedRoomId) : null;

  // Get related rooms for selected room
  const relatedRooms = useMemo(() => {
    if (!selectedRoom || !graphData?.edges) return [];
    
    return graphData.edges
      .filter(edge =>
        String(edge.source_room_id) === selectedRoom.id ||
        String(edge.target_room_id) === selectedRoom.id
      )
      .map(edge => {
        const otherId = String(edge.source_room_id) === selectedRoom.id ?
          String(edge.target_room_id) : String(edge.source_room_id);
        const other = roomById.get(otherId);
        return {
          id: otherId,
          name: other?.name || "Unknown",
          overlap: edge.overlap_count || 0,
        };
      });
  }, [selectedRoom, graphData, roomById]);

  const handleRecenter = () => {
    if (!rfInstance) return;
    rfInstance.fitView({ padding: 0.2, duration: 350 });
  };

  const handleNodeHover = (event, node) => {
    if (!canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    setHoverPos({
      x: event.clientX - rect.left + 12,
      y: event.clientY - rect.top + 12,
    });
    setHoveredRoom(roomById.get(node.id));
  };

  // Loading state
  if (loading) {
    return (
      <div className="org-graph-shell">
        <div style={{ padding: "40px", textAlign: "center", color: "var(--text-secondary)" }}>
          <div style={{ fontSize: "24px", marginBottom: "8px" }}>🔄</div>
          <div>Loading organization data...</div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="org-graph-shell">
        <div style={{ padding: "40px", textAlign: "center" }}>
          <div style={{ fontSize: "24px", marginBottom: "8px", color: "#ef4444" }}>⚠️</div>
          <div style={{ color: "var(--text)", marginBottom: "4px", fontWeight: 600 }}>
            Unable to load organization data
          </div>
          <div style={{ color: "var(--text-secondary)", fontSize: "13px" }}>
            {error}
          </div>
          <button 
            onClick={fetchOrgData}
            style={{ marginTop: "16px", padding: "8px 16px", cursor: "pointer" }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Empty state
  if (!graphData || processedRooms.length === 0) {
    return (
      <div className="org-graph-shell">
        <div style={{ padding: "40px", textAlign: "center", color: "var(--text-secondary)" }}>
          <div style={{ fontSize: "24px", marginBottom: "8px" }}>📊</div>
          <div>No organization data available</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`org-graph-page-wrapper ${sidebarExpanded ? "sidebar-open" : ""}`}>
      {/* LEFT PANEL - overlay */}
      <div className={`org-members-panel ${sidebarExpanded ? "expanded" : ""}`}>
        <button className="sidebar-toggle" onClick={() => setSidebarExpanded(!sidebarExpanded)}>
          {sidebarExpanded ? "←" : "→"} Team
        </button>
        <div className="panel-header">
          <h3>Team Members</h3>
          <span className="member-count">{allMembers.length} total</span>
        </div>

        <div className="members-list">
          {allMembers.length === 0 ? (
            <div className="empty-state">Loading members...</div>
          ) : (
            allMembers.map((member) => {
              const memberRooms = getMemberRooms(member.id);
              return (
                <div
                  key={member.id}
                  className="member-item"
                  onClick={() => {
                    console.log("[OrgGraph] Selected member:", member.name, "in rooms:", memberRooms);
                  }}
                >
                  <div className="member-info">
                    <span className="member-name">{member.name}</span>
                    <span className="member-email">{member.email}</span>
                  </div>
                  {memberRooms.length > 0 && (
                    <div className="member-rooms-badges">
                      {memberRooms.map((room) => (
                        <span key={room.id} className="room-badge">
                          {room.name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Backdrop when sidebar open */}
      {sidebarExpanded && <div className="sidebar-backdrop" onClick={() => setSidebarExpanded(false)} />}

      <div className="org-graph-shell-3col">
        {/* CENTER PANEL - Org Graph */}
        <div className="org-graph-center">
          <div className="org-graph-toolbar">
            <div className="toolbar-left">
              <input
                className="org-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search rooms..."
              />
              <select
                className="org-select"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                {STATUS_ORDER.map((status) => (
                  <option key={status} value={status}>
                    {status === "all" ? "All statuses" : status}
                  </option>
                ))}
              </select>
              <select
                className="org-select"
                value={timeWindow}
                onChange={(e) => setTimeWindow(e.target.value)}
              >
                <option value="24h">Last 24h</option>
                <option value="7d">Last 7 days</option>
                <option value="30d">Last 30 days</option>
                <option value="90d">Last 90 days</option>
              </select>
            </div>
            <div className="toolbar-right">
              <label className="org-toggle">
                <input
                  type="checkbox"
                  checked={showSentiment}
                  onChange={() => setShowSentiment((v) => !v)}
                />
                Sentiment
              </label>
              <label className="org-toggle">
                <input
                  type="checkbox"
                  checked={showFires}
                  onChange={() => setShowFires((v) => !v)}
                />
                Fires
              </label>
              <label className="org-toggle">
                <input
                  type="checkbox"
                  checked={showOverdue}
                  onChange={() => setShowOverdue((v) => !v)}
                />
                Overdue
              </label>
              <label className="org-toggle">
                <input
                  type="checkbox"
                  checked={showLastActive}
                  onChange={() => setShowLastActive((v) => !v)}
                />
                Activity
              </label>
              <button
                className="toolbar-btn toolbar-btn-create"
                onClick={() => setShowCreateRoom(true)}
              >
                + New Room
              </button>
              <button className="toolbar-btn" onClick={handleRecenter}>
                Recenter
              </button>
            </div>
          </div>

          {/* Create Room Modal */}
          {showCreateRoom && (
            <div className="modal-overlay" onClick={() => setShowCreateRoom(false)}>
              <div className="modal-content" onClick={(e) => e.stopPropagation()}>
                <h3>Create New Room</h3>
                <input
                  type="text"
                  placeholder="Enter room name..."
                  value={newRoomName}
                  onChange={(e) => setNewRoomName(e.target.value)}
                  onKeyPress={(e) => {
                    if (e.key === "Enter" && !creatingRoom) {
                      createNewRoom();
                    }
                  }}
                  className="room-name-input"
                  autoFocus
                />
                <div className="modal-actions">
                  <button
                    onClick={() => setShowCreateRoom(false)}
                    className="btn-cancel"
                    disabled={creatingRoom}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={createNewRoom}
                    className="btn-create"
                    disabled={creatingRoom || !newRoomName.trim()}
                  >
                    {creatingRoom ? "Creating..." : "Create Room"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Graph Canvas */}
          <div className="org-graph-canvas" ref={canvasRef}>
            {hoveredRoom && (
              <div
                className="org-node-tooltip"
                style={{ left: hoverPos.x, top: hoverPos.y }}
              >
                <div className="tooltip-title">{hoveredRoom.name}</div>
                <div className="tooltip-meta">
                  {hoveredRoom.status} • {hoveredRoom.memberCount} members
                </div>
              </div>
            )}
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onInit={setRfInstance}
              onNodeClick={(_, node) => {
                const room = roomById.get(node.id);
                setSelectedRoomId(node.id);
                setSelectedRoomForEdit(room);
                fetchRoomDetails(node.id);
              }}
              onNodeMouseEnter={handleNodeHover}
              onNodeMouseLeave={() => setHoveredRoom(null)}
              onPaneClick={() => {
                setSelectedRoomId(null);
                setSelectedRoomForEdit(null);
                setRoomDetails(null);
              }}
              fitView
              fitViewOptions={{ padding: 0.2 }}
            >
              <Background gap={24} color="rgba(148, 163, 184, 0.35)" />
              <MiniMap
                nodeColor={(node) => {
                  const status = node?.data?.status?.toLowerCase?.() || "healthy";
                  if (status === "critical") return "#ef4444";
                  if (status === "strained") return "#f59e0b";
                  return "#10b981";
                }}
                nodeStrokeWidth={2}
                zoomable
                pannable
              />
              <Controls />
            </ReactFlow>
          </div>
        </div>

        {/* RIGHT PANEL - Room Management */}
        {selectedRoomForEdit && (
          <div className="org-room-management">
            <div className="panel-header">
              <div>
                <h3>{selectedRoomForEdit.name}</h3>
                <span className={`status-badge ${selectedRoomForEdit.status.toLowerCase()}`}>
                  {selectedRoomForEdit.status}
                </span>
              </div>
              <button
                onClick={() => deleteRoom(selectedRoomForEdit.id, selectedRoomForEdit.name)}
                className="btn-delete-room"
                disabled={deletingRoom}
                title="Delete this room"
              >
                {deletingRoom ? "Deleting..." : "🗑️ Delete Room"}
              </button>
            </div>

            {/* Room Stats */}
            <div className="room-stats">
              <div className="stat-item">
                <span className="stat-label">Members</span>
                <span className="stat-value">{selectedRoomForEdit.memberCount || 0}</span>
              </div>
              <div className="stat-item">
                <span className="stat-label">Conflicts</span>
                <span className="stat-value">{selectedRoomForEdit.fires || 0}</span>
              </div>
              <div className="stat-item">
                <span className="stat-label">Overdue</span>
                <span className="stat-value">{selectedRoomForEdit.overdue || 0}</span>
              </div>
            </div>

            {/* Current Members */}
            <div className="room-section">
              <h4>Current Members</h4>
              <div className="room-members-list">
                {selectedRoomForEdit.memberIds && selectedRoomForEdit.memberIds.length > 0 ? (
                  selectedRoomForEdit.memberIds.map((memberId) => {
                    const member = getMemberDetails(memberId);
                    if (!member) return null;

                    return (
                      <div key={memberId} className="room-member-row">
                        <div className="member-details">
                          <span className="member-name">{member.name}</span>
                          <span className="member-email">{member.email}</span>
                        </div>
                        <button
                          onClick={() => removeMemberFromRoom(memberId, selectedRoomForEdit.id)}
                          className="btn-remove"
                          disabled={removingMember}
                          title="Remove from room"
                        >
                          ✕
                        </button>
                      </div>
                    );
                  })
                ) : (
                  <div className="empty-state">No members in this room</div>
                )}
              </div>
            </div>

            {/* Add Member */}
            <div className="room-section">
              <h4>Add Member</h4>
              <select
                onChange={(e) => {
                  if (e.target.value) {
                    addMemberToRoom(e.target.value, selectedRoomForEdit.id);
                    e.target.value = "";
                  }
                }}
                disabled={addingMember}
                className="add-member-select"
              >
                <option value="">{addingMember ? "Adding..." : "Select member to add..."}</option>
                {allMembers
                  .filter((m) => !selectedRoomForEdit.memberIds?.includes(m.id))
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} ({m.email})
                    </option>
                  ))}
              </select>
            </div>

            {/* Related Rooms */}
            {relatedRooms.length > 0 && (
              <div className="room-section">
                <h4>Related Rooms</h4>
                <ul className="related-rooms-list">
                  {relatedRooms.map((room) => (
                    <li key={room.id} className="related-room-item">
                      <span>{room.name}</span>
                      <span className="overlap-badge">{room.overlap} shared</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ROOM DETAILS VIEW - Below */}
      {selectedRoomForEdit && roomDetails && (
        <div className="room-details-expanded">
          <div className="room-details-header">
            <h2>{selectedRoomForEdit.name} - Detailed View</h2>
            <button
              onClick={() => {
                setSelectedRoomId(null);
                setSelectedRoomForEdit(null);
                setRoomDetails(null);
              }}
              className="close-details-btn"
            >
              Close Details
            </button>
          </div>

          {loadingDetails ? (
            <div className="details-loading">
              <div className="loading-spinner">🔄</div>
              <p>Loading room details...</p>
            </div>
          ) : (
            <div className="room-details-grid">
              <div className="details-section">
                <h3>📊 Room Stats</h3>
                <div className="stats-grid">
                  <div className="stat-item">
                    <span className="stat-label">Members</span>
                    <span className="stat-value">
                      {roomDetails?.member_count ?? (selectedRoomForEdit.memberIds || []).length}
                    </span>
                  </div>
                  <div className="stat-item">
                    <span className="stat-label">Last Active</span>
                    <span className="stat-value">
                      {roomDetails?.last_active
                        ? new Date(roomDetails.last_active).toLocaleDateString()
                        : "Never"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="details-section details-section-wide">
                <h3>💬 Recent Activity</h3>
                {roomDetails.recent_messages && roomDetails.recent_messages.length > 0 ? (
                  <div className="recent-messages">
                    {roomDetails.recent_messages.map((msg) => (
                      <div key={msg.id} className="message-preview">
                        <p className="message-content">{msg.content}</p>
                        <span className="message-time">
                          {msg.created_at ? new Date(msg.created_at).toLocaleString() : "Unknown time"}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="empty-section">No recent activity</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
