import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useEdgesState,
  useNodesState,
} from "reactflow";
import "reactflow/dist/style.css";
import "./GraphView.css";
import PipelineNode from "../components/graphs/PipelineNode";
import AdminErrorBoundary from "../components/admin/AdminErrorBoundary";

const MotionDiv = motion.div;

const DEFAULT_PIPELINE = {
  nodes: [
    { id: "email_ingest", label: "Email Ingestion", type: "email_ingest" },
    { id: "vector_search", label: "Vector Search", type: "vector_search" },
    { id: "reranker", label: "Reranker", type: "reranker" },
    { id: "task_extract", label: "Task Extraction", type: "task_extract" },
    { id: "brief_gen", label: "Brief Generation", type: "brief_gen" },
  ],
  edges: [
    { source: "email_ingest", target: "vector_search" },
    { source: "vector_search", target: "reranker" },
    { source: "reranker", target: "task_extract" },
    { source: "task_extract", target: "brief_gen" },
  ],
};

function transformPipelineToGraph(pipeline, diff) {
  const nodes = (pipeline?.nodes || []).map((node, idx) => {
    const x = (idx % 3) * 220 + 60;
    const y = Math.floor(idx / 3) * 160 + 80;
    const status = node.status || "pending";
    const diffStyle =
      diff?.added?.includes(node.id) ? "added" :
      diff?.removed?.includes(node.id) ? "removed" :
      diff?.modified?.includes(node.id) ? "modified" : null;
    return {
      id: node.id,
      type: "pipeline",
      position: { x, y },
      data: {
        label: node.label || node.id,
        type: node.type,
        status,
        executionTime: node.executionTime,
      },
      style: diffStyle === "added"
        ? { border: "2px solid #10b981" }
        : diffStyle === "removed"
        ? { border: "2px solid #ef4444" }
        : diffStyle === "modified"
        ? { border: "2px solid #f59e0b" }
        : undefined,
    };
  });

  const edges = (pipeline?.edges || []).map((edge) => ({
    id: `e-${edge.source}-${edge.target}`,
    source: edge.source,
    target: edge.target,
    type: "smoothstep",
  }));

  return { nodes, edges };
}

function GraphChat({ agentId, onProposedChange }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [proposedChange, setProposedChange] = useState(null);
  const [sending, setSending] = useState(false);

  const sendMessage = async () => {
    if (!input.trim()) return;
    const userMsg = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);

    try {
      const response = await fetch(`/api/v1/graphs/${agentId || "test-agent"}/modify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ request: userMsg.content }),
      });
      const data = await response.json().catch(() => ({}));
      const payload = data?.data || data || {};
      if (data?.success) {
        setProposedChange(payload);
        if (payload.explanation) {
          setMessages((prev) => [...prev, { role: "agent", content: payload.explanation }]);
        }
        onProposedChange?.(payload);
      } else {
        setMessages((prev) => [...prev, { role: "agent", content: data?.error || "Request failed" }]);
      }
    } catch (err) {
      setMessages((prev) => [...prev, { role: "agent", content: err?.message || "Network error" }]);
    } finally {
      setSending(false);
    }
  };

  const approveChange = () => {
    if (proposedChange?.pipeline) {
      onProposedChange?.(proposedChange);
    }
    setProposedChange(null);
  };

  return (
    <div className="chat-panel">
      <div className="messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
      </div>

      {proposedChange && (
        <div className="proposed-change">
          <h4>Proposed Changes</h4>
          <pre>{JSON.stringify(proposedChange?.diff || proposedChange, null, 2)}</pre>
          <div className="proposed-actions">
            <button onClick={approveChange}>Approve</button>
            <button onClick={() => setProposedChange(null)}>Reject</button>
          </div>
        </div>
      )}

      <div className="input-area">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Tell the agent what to change..."
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
        />
        <button onClick={sendMessage} disabled={sending}>
          {sending ? "Sending..." : "Send"}
        </button>
      </div>
    </div>
  );
}

export default function GraphView() {
  const { agentId: routeAgentId } = useParams();
  const resolvedAgentId = routeAgentId || null;
  const [pipeline, setPipeline] = useState(DEFAULT_PIPELINE);
  const [diff, setDiff] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [executionStatus, setExecutionStatus] = useState(null);
  const [nodeRuns, setNodeRuns] = useState({});
  const [executionId, setExecutionId] = useState(null);
  const lastEventIdRef = useRef(null);
  const pollTimerRef = useRef(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const eventSourceRef = useRef(null);

  const applyPipeline = useCallback(
    (pipe, nextDiff) => {
      const { nodes: n, edges: e } = transformPipelineToGraph(pipe, nextDiff);
      setNodes(n);
      setEdges(e);
    },
    [setNodes, setEdges]
  );

  useEffect(() => {
    applyPipeline(pipeline, diff);
  }, [pipeline, diff, applyPipeline]);

  const resetNodeRuns = useCallback((pipe) => {
    const list = pipe?.nodes || [];
    const next = {};
    list.forEach((n) => {
      next[n.id] = { status: "queued", lastOutputPreview: null, lastError: null, startedAt: null, completedAt: null };
    });
    setNodeRuns(next);
  }, []);

  const applyGraphEvent = useCallback((evt) => {
    if (!evt || !evt.event_type) return;
    if (evt.event_id && lastEventIdRef.current === evt.event_id) {
      return;
    }
    if (evt.event_id) {
      lastEventIdRef.current = evt.event_id;
    }
    const type = evt.event_type;
    const payload = evt.payload || {};
    if (type === "graph.execution.started") {
      resetNodeRuns(pipeline);
      setExecutionStatus({ status: "running", startedAt: Date.now(), requestId: evt.request_id || null });
      setExecutionId(payload?.execution_id || payload?.run_id || null);
      return;
    }
    if (type === "graph.execution.completed") {
      setExecutionStatus((prev) => ({
        ...(prev || {}),
        status: "completed",
        completedAt: Date.now(),
        requestId: evt.request_id || null,
      }));
      setExecutionId(payload?.execution_id || payload?.run_id || executionId);
      return;
    }
    if (type.startsWith("graph.node.")) {
      const nodeId = payload.node_id;
      if (!nodeId) return;
      setNodeRuns((prev) => {
        const existing = prev[nodeId] || {};
        if (type === "graph.node.started") {
          return { ...prev, [nodeId]: { ...existing, status: "running", startedAt: Date.now(), lastError: null } };
        }
        if (type === "graph.node.completed") {
          return {
            ...prev,
            [nodeId]: {
              ...existing,
              status: "completed",
              completedAt: Date.now(),
              lastOutputPreview: payload.output_preview || existing.lastOutputPreview || null,
              outputRef: payload.output_ref || existing.outputRef,
            },
          };
        }
        if (type === "graph.node.failed") {
          return {
            ...prev,
            [nodeId]: {
              ...existing,
              status: "failed",
              completedAt: Date.now(),
              lastError: payload.error || payload.message || existing.lastError,
            },
          };
        }
        return prev;
      });
    }
  }, [pipeline, resetNodeRuns]);

  const fetchPipeline = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const endpoint = resolvedAgentId ? `/api/v1/graphs/${resolvedAgentId}` : "/api/v1/graphs/me";
      const res = await fetch(endpoint, {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const payload = data?.data || data || DEFAULT_PIPELINE;
      setPipeline(payload.pipeline || payload);
      resetNodeRuns(payload.pipeline || payload);
      setDiff(null);
    } catch (err) {
      console.error("[GraphView] Failed to fetch pipeline:", err);
      setError(err);
      setPipeline(DEFAULT_PIPELINE);
    } finally {
      setLoading(false);
    }
  }, [resolvedAgentId]);

  useEffect(() => {
    fetchPipeline();
  }, [fetchPipeline]);

  useEffect(() => {
    if (eventSourceRef.current) return;
    const es = new EventSource("/api/v1/events", { withCredentials: true });
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        applyGraphEvent(data);
        if (data.event_type === "graph.pipeline.modified") {
          setDiff(data.payload?.diff || null);
          if (data.payload?.new_pipeline) {
            setPipeline(data.payload.new_pipeline);
          }
        }
      } catch (err) {
        console.warn("[GraphView] SSE parse error:", err);
      }
    };
    es.onerror = (err) => {
      console.warn("[GraphView] SSE error:", err);
    };
    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [applyGraphEvent]);

  const pollEvents = useCallback(
    async (agentId) => {
      if (!agentId) return;
      try {
        const qs = lastEventIdRef.current ? `?after=${encodeURIComponent(lastEventIdRef.current)}` : "";
        const res = await fetch(`/api/v1/graphs/${agentId}/events${qs}`, { credentials: "include" });
        if (!res.ok) return;
        const events = await res.json().catch(() => []);
        if (Array.isArray(events)) {
          events.forEach((evt) => applyGraphEvent(evt));
        }
      } catch (err) {
        console.warn("[GraphView] Event poll failed:", err?.message || err);
      }
    },
    [applyGraphEvent]
  );

  useEffect(() => {
    if (executionStatus?.status === "running" && resolvedAgentId) {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      pollTimerRef.current = setInterval(() => pollEvents(resolvedAgentId), 1500);
    } else {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    }
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [executionStatus, pollEvents, resolvedAgentId]);

  const executePipeline = async () => {
    if (loading) return;
    const targetId = resolvedAgentId || "me";
    try {
      setExecutionStatus({ status: "running", startedAt: Date.now(), requestId: null });
      resetNodeRuns(pipeline);
      const res = await fetch(`/api/v1/graphs/${targetId}/execute`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || json?.success === false) {
        throw new Error(json?.error || `Execute failed (${res.status})`);
      }
      const execId = json?.data?.execution_id || json?.data?.run_id || null;
      setExecutionId(execId);
      setExecutionStatus((prev) => ({ ...(prev || {}), requestId: json?.request_id || prev?.requestId || null, executionId: execId }));
    } catch (err) {
      console.error("[GraphView] Execute failed:", err);
      setExecutionStatus({ status: "failed", error: err?.message || "Execute failed" });
    }
  };

  const handleProposedChange = (change) => {
    if (change?.pipeline) {
      const newPipeline = change.pipeline;
      const newDiff = {
        added: change.diff?.added || [],
        removed: change.diff?.removed || [],
        modified: change.diff?.modified || [],
      };
      setDiff(newDiff);
      setPipeline(newPipeline);
    }
  };

  const inspector = useMemo(() => {
    if (!selectedNode) return null;
    const run = nodeRuns[selectedNode.id] || {};
    const startedAt = run.startedAt ? new Date(run.startedAt) : null;
    const completedAt = run.completedAt ? new Date(run.completedAt) : null;
    const duration = startedAt && completedAt ? `${completedAt - startedAt} ms` : "—";
    return (
      <div className="node-inspector">
        <h3>{selectedNode.data?.label}</h3>
        <div className="node-details">
          <div>Type: {selectedNode.data?.type}</div>
          <div>Status: {run.status || "pending"}</div>
          <div>Started: {startedAt ? startedAt.toLocaleTimeString() : "—"}</div>
          <div>Completed: {completedAt ? completedAt.toLocaleTimeString() : "—"}</div>
          <div>Duration: {duration}</div>
          {run.lastOutputPreview && (
            <div>
              <h4>Output Preview:</h4>
              <pre>{JSON.stringify(run.lastOutputPreview, null, 2)}</pre>
            </div>
          )}
          {run.lastError && (
            <div>
              <h4>Error:</h4>
              <pre>{JSON.stringify(run.lastError, null, 2)}</pre>
            </div>
          )}
          {run.outputRef && (
            <button
              className="refresh-btn"
              onClick={() => {
                // placeholder for full output fetch
                console.log("[GraphView] View full output ref:", run.outputRef);
              }}
              style={{ marginTop: 8 }}
            >
              View full output
            </button>
          )}
        </div>
      </div>
    );
  }, [nodeRuns, selectedNode]);

  const nodeTypesMemo = useMemo(
    () => ({
      pipeline: (props) => <PipelineNode {...props} nodeRun={nodeRuns[props.id]} />,
    }),
    [nodeRuns]
  );

  return (
    <AdminErrorBoundary tabName="Graph View">
      <div className="graph-view">
        <div className="graph-panel">
          <div className="graph-toolbar">
            <div>
              <h2>Agent Pipeline</h2>
              <p className="subhead">Agent ID: {resolvedAgentId || "me"}</p>
              {executionStatus && <p className="subhead">Execution: {executionStatus.status || "idle"} {executionId ? `(id: ${executionId})` : ""}</p>}
            </div>
            <div className="graph-actions">
              <button onClick={fetchPipeline} disabled={loading}>
                {loading ? "Loading..." : "Refresh"}
              </button>
              <button onClick={executePipeline}>Execute</button>
            </div>
          </div>

          {error && (
            <div className="graph-error">
              <div style={{ fontWeight: 600 }}>Failed to load pipeline</div>
              <div style={{ fontSize: 12 }}>{error.message || "Unknown error"}</div>
            </div>
          )}

          <AnimatePresence>
            <MotionDiv
              key="reactflow"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="reactflow-wrapper"
            >
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeClick={(_, node) => setSelectedNode(node)}
                nodeTypes={nodeTypesMemo}
                fitView
              >
                <Background />
                <MiniMap />
                <Controls />
              </ReactFlow>
            </MotionDiv>
          </AnimatePresence>
        </div>

        <div className="chat-panel-shell">
          <GraphChat agentId={resolvedAgentId || "test-agent"} onProposedChange={handleProposedChange} />
          {inspector}
        </div>
      </div>
    </AdminErrorBoundary>
  );
}
