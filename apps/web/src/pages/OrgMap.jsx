import { useEffect, useState, useCallback, useMemo } from "react";
import {
  ReactFlow, 
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./OrgMap.css";
import { API_BASE_URL } from "../config";
import RoomNode from "../components/graph/RoomNode";
import RoomDetailPanel from "../components/graph/RoomDetailPanel";

const nodeTypes = { roomNode: RoomNode };

export default function OrgMap() {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedRoom, setSelectedRoom] = useState(null);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE_URL}/api/org/graph`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to load org graph");
      const data = await res.json();
      const nextNodes = (data.rooms || data.nodes || []).map((room, idx) => {
        const canonicalId =
          (room.slug || room.id || room.name || `room-${idx}`).toLowerCase();
        return {
          id: canonicalId,
          type: "roomNode",
          position: {
            x: (idx % 4) * 240 + Math.random() * 40,
            y: Math.floor(idx / 4) * 160 + Math.random() * 40,
          },
          data: {
            id: canonicalId,
            displayName: room.name || room.id || "Room",
            name: room.name,
            fires: room.fires,
            sentiment: room.sentiment,
            overdue: room.overdue,
            status: room.status,
            onOpen: setSelectedRoom,
          },
        };
      });
      const nextEdges = (data.edges || []).map((edge, idx) => {
        const source = (edge.source || "").toLowerCase();
        const target = (edge.target || "").toLowerCase();
        const weightLabel =
          edge.weight?.toFixed && !isNaN(edge.weight)
            ? edge.weight.toFixed(2)
            : edge.weight ?? "";
        return {
          id: `${source}-${target}-${idx}`,
          source,
          target,
          label: (
            <span
              title={`${edge.source} → ${edge.target} (dependency weight ${weightLabel})`}
            >
              {weightLabel}
            </span>
          ),
          data: {
            rawSource: edge.source,
            rawTarget: edge.target,
            weightLabel,
          },
        };
      });
      setNodes(nextNodes);
      setEdges(nextEdges);
    } catch (err) {
      console.error("Org graph failed", err);
      setError("Could not load org graph.");
    } finally {
      setLoading(false);
    }
  }, [setNodes, setEdges]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  const onNodeClick = useCallback((_, node) => {
    if (node?.data) setSelectedRoom(node.data);
  }, []);

  const displayedEdges = useMemo(() => {
    if (!selectedRoom) {
      return edges.map((e) => ({
        ...e,
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--text)" },
        style: { stroke: "var(--text)" },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 6,
      }));
    }
    return edges.map((e) => {
      const isOutgoing = e.source === selectedRoom.id;
      const isIncoming = e.target === selectedRoom.id;
      return {
        ...e,
        markerEnd: { type: MarkerType.ArrowClosed, color: isOutgoing ? "#0a8" : "var(--text)" },
        style: {
          stroke: isOutgoing ? "#0a8" : isIncoming ? "#888" : "var(--border)",
          strokeWidth: isOutgoing || isIncoming ? 2.4 : 1.2,
          opacity: isOutgoing || isIncoming ? 1 : 0.4,
        },
        labelStyle: { fill: "var(--text)" },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 6,
      };
    });
  }, [edges, selectedRoom]);

  const upstream = useMemo(() => {
    if (!selectedRoom) return [];
    return edges
      .filter((e) => e.target === selectedRoom.id)
      .map((e) => e.data?.rawSource || e.source);
  }, [edges, selectedRoom]);

  const downstream = useMemo(() => {
    if (!selectedRoom) return [];
    return edges
      .filter((e) => e.source === selectedRoom.id)
      .map((e) => e.data?.rawTarget || e.target);
  }, [edges, selectedRoom]);

  return (
    <div className="org-map-shell">
      <div className="org-map-header">
        <div>
          <h2>Organization</h2>
          <p className="subhead">Rooms, status, and dependencies.</p>
        </div>
        <div className="org-map-actions">
          <button className="btn" onClick={loadGraph} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && <div className="auth-status">{error}</div>}

      <div className="org-map-legend">
        <div>Lines represent dependencies between rooms.</div>
        <div>Numbers are normalized weights between 0 and 1.</div>
      </div>

      <div className="org-map-canvas">
        <ReactFlow
          nodes={nodes}
          edges={displayedEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          onNodeClick={onNodeClick}
          fitView
        >
          <Background />
          <MiniMap />
          <Controls />
        </ReactFlow>
      </div>

      <RoomDetailPanel
        room={selectedRoom}
        onClose={() => setSelectedRoom(null)}
        upstream={upstream}
        downstream={downstream}
      />
    </div>
  );
}
