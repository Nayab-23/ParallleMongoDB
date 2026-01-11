import { useState } from "react";
import "./Timeline.css";

const mockData = {
  daily: [
    {
      id: 1,
      time: "9:00 AM",
      title: "Review sprint progress with engineering team",
      assignee: "Alice Chen",
      priority: "high",
      status: "pending",
    },
    {
      id: 2,
      time: "2:00 PM",
      title: "Client demo preparation and stakeholder sync",
      assignee: "Bob Smith",
      priority: "medium",
      status: "in_progress",
    },
    {
      id: 3,
      time: "4:30 PM",
      title: "Product roadmap alignment meeting",
      assignee: "Emma Johnson",
      priority: "high",
      status: "completed",
    },
  ],
  weekly: [
    {
      id: 1,
      title: "Complete Q1 feature launch planning",
      dueDate: "Jan 15, 2026",
      progress: 65,
      owner: "Product Team",
      status: "on_track",
    },
    {
      id: 2,
      title: "User research synthesis and insights presentation",
      dueDate: "Jan 12, 2026",
      progress: 40,
      owner: "Design Team",
      status: "at_risk",
    },
    {
      id: 3,
      title: "Technical debt reduction initiative kickoff",
      dueDate: "Jan 17, 2026",
      progress: 85,
      owner: "Engineering Team",
      status: "on_track",
    },
  ],
  monthly: [
    {
      id: 1,
      title: "Launch mobile app v2.0 with new authentication flow",
      milestone: "Q1 2026 Major Release",
      progress: 55,
      teams: ["Engineering", "Product", "Design"],
      status: "on_track",
    },
    {
      id: 2,
      title: "Scale infrastructure for 10x traffic growth",
      milestone: "Infrastructure Modernization",
      progress: 30,
      teams: ["Engineering", "Operations"],
      status: "at_risk",
    },
    {
      id: 3,
      title: "Establish new partner integration framework",
      milestone: "Ecosystem Expansion",
      progress: 75,
      teams: ["Product", "Engineering", "Sales"],
      status: "on_track",
    },
  ],
};

const priorityColors = {
  high: "#ef4444",
  medium: "#f59e0b",
  low: "#10b981",
};

const statusColors = {
  pending: "#6b7280",
  in_progress: "#3b82f6",
  completed: "#10b981",
  on_track: "#10b981",
  at_risk: "#ef4444",
};

const statusLabels = {
  pending: "Pending",
  in_progress: "In Progress",
  completed: "Completed",
  on_track: "On Track",
  at_risk: "At Risk",
};

export default function Timeline() {
  const [activeSection, setActiveSection] = useState("daily");

  return (
    <div className="timeline-container">
      <div className="timeline-header">
        <h2>Project Timeline</h2>
        <div className="timeline-tabs">
          <button
            className={activeSection === "daily" ? "active" : ""}
            onClick={() => setActiveSection("daily")}
          >
            Daily Goals
          </button>
          <button
            className={activeSection === "weekly" ? "active" : ""}
            onClick={() => setActiveSection("weekly")}
          >
            Weekly Focus
          </button>
          <button
            className={activeSection === "monthly" ? "active" : ""}
            onClick={() => setActiveSection("monthly")}
          >
            Monthly Objectives
          </button>
        </div>
      </div>

      <div className="timeline-content">
        {activeSection === "daily" && (
          <div className="daily-section">
            {mockData.daily.map((item) => (
              <div key={item.id} className="timeline-card">
                <div className="card-header">
                  <span className="time-badge">{item.time}</span>
                  <span
                    className="status-badge"
                    style={{ background: statusColors[item.status] }}
                  >
                    {statusLabels[item.status]}
                  </span>
                </div>
                <h3>{item.title}</h3>
                <div className="card-footer">
                  <span className="assignee">👤 {item.assignee}</span>
                  <span
                    className="priority-badge"
                    style={{ borderColor: priorityColors[item.priority] }}
                  >
                    {item.priority.toUpperCase()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {activeSection === "weekly" && (
          <div className="weekly-section">
            {mockData.weekly.map((item) => (
              <div key={item.id} className="timeline-card">
                <div className="card-header">
                  <span className="due-badge">Due: {item.dueDate}</span>
                  <span
                    className="status-badge"
                    style={{ background: statusColors[item.status] }}
                  >
                    {statusLabels[item.status]}
                  </span>
                </div>
                <h3>{item.title}</h3>
                <div className="progress-section">
                  <div className="progress-bar-wrapper">
                    <div
                      className="progress-bar-fill"
                      style={{ width: `${item.progress}%` }}
                    >
                      {item.progress}%
                    </div>
                  </div>
                </div>
                <div className="card-footer">
                  <span className="owner">🏢 {item.owner}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {activeSection === "monthly" && (
          <div className="monthly-section">
            {mockData.monthly.map((item) => (
              <div key={item.id} className="timeline-card">
                <div className="card-header">
                  <span className="milestone-badge">{item.milestone}</span>
                  <span
                    className="status-badge"
                    style={{ background: statusColors[item.status] }}
                  >
                    {statusLabels[item.status]}
                  </span>
                </div>
                <h3>{item.title}</h3>
                <div className="progress-section">
                  <div className="progress-bar-wrapper">
                    <div
                      className="progress-bar-fill"
                      style={{ width: `${item.progress}%` }}
                    >
                      {item.progress}%
                    </div>
                  </div>
                </div>
                <div className="card-footer">
                  <div className="teams-list">
                    {item.teams.map((team, idx) => (
                      <span key={idx} className="team-tag">
                        {team}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
