import React from "react";
import { useNavigate } from "react-router-dom";
import "./SystemAgentChatItem.css";

export default function SystemAgentChatItem({ chat }) {
  const navigate = useNavigate();
  const graphId = chat.graph_id || chat.id || chat.chat_id;

  function openGraph() {
    if (graphId) {
      window.open(`/graphs/${graphId}`, "_blank");
    } else {
      navigate("/graphs");
    }
  }

  return (
    <div className="system-agent-chat-item">
      <div className="system-agent-header">
        <span className="system-agent-icon">🧪</span>
        <div className="system-agent-info">
          <h4 className="system-agent-title">{chat.title || "System Agent (Experimental)"}</h4>
          {chat.subtitle && (
            <p className="system-agent-subtitle">{chat.subtitle}</p>
          )}
        </div>
      </div>

      <button className="view-graph-button" onClick={openGraph}>
        View Graph →
      </button>
    </div>
  );
}
