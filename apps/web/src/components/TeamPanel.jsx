import { useEffect, useState, useRef } from "react";
import "./TeamPanel.css";

const statusColor = {
  active: "active",
  idle: "idle",
  offline: "offline",
};

export default function TeamPanel({ user = { name: "You" }, statuses = [] }) {
  const members = statuses.length
    ? statuses
    : [
        { name: user.name || "You", role: "In chat", state: "active" },
        { name: "Coordinator", role: "Orchestrating replies", state: "idle" },
      ];

  const [hovered, setHovered] = useState(null);
  const [hoverTimer, setHoverTimer] = useState(null); // A
  const [drawerPos, setDrawerPos] = useState({ top: 0, left: 0 });
  const memberRefs = useRef({}); // A

  const startHover = (member, event) => {
    if (hoverTimer) clearTimeout(hoverTimer);
    const timer = setTimeout(() => {
      const rect = event.currentTarget.getBoundingClientRect();
      setDrawerPos({
        top: rect.top,
        left: rect.right + 12,
      });
      setHovered(member);
    }, 500);
    setHoverTimer(timer);
  };

  const endHover = () => {
    if (hoverTimer) clearTimeout(hoverTimer);
    setHovered(null);
  };

  useEffect(() => {
    return () => {
      if (hoverTimer) clearTimeout(hoverTimer);
    };
  }, [hoverTimer]);

  return (
    <div className="team-panel">
      <div className="team-list">
        {members.map((m) => (
          <div
            className="team-member"
            key={m.name}
            ref={(el) => (memberRefs.current[m.name] = el)}
            onMouseEnter={(e) => startHover(m, e)}
            onMouseLeave={endHover}
          >
            <div className={`status-dot ${statusColor[m.state] || "idle"}`} />
            <div className="team-member-text">
              <span className="team-member-name">{m.name}</span>
            </div>
          </div>
        ))}
      </div>

      <div
        className={`activity-drawer ${hovered ? "open" : ""}`}
        style={{
          top: `${drawerPos.top}px`,
          left: `${drawerPos.left}px`,
        }}
        onMouseEnter={() => hovered && setHovered(hovered)}
        onMouseLeave={endHover}
      >
        {hovered && (
          <div className="activity-card">
            <div className="activity-name">{hovered.name}</div>
            <div className="activity-text">
              Working on:{" "}
              {truncate(
                hovered.activity || hovered.role || "No recent activity",
                60
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function truncate(text, max) {
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}…` : text;
}