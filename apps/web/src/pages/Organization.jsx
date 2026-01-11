import { useCallback, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
} from "reactflow";
import "reactflow/dist/style.css";
import "./Organization.css";

const initialNodes = [
  {
    id: "1",
    type: "default",
    data: { label: "Engineering" },
    position: { x: 250, y: 50 },
    style: { background: "#3b82f6", color: "white", border: "2px solid #2563eb", borderRadius: "8px", padding: "16px", fontWeight: 600 },
  },
  {
    id: "2",
    type: "default",
    data: { label: "Product" },
    position: { x: 500, y: 50 },
    style: { background: "#3b82f6", color: "white", border: "2px solid #2563eb", borderRadius: "8px", padding: "16px", fontWeight: 600 },
  },
  {
    id: "3",
    type: "default",
    data: { label: "Design" },
    position: { x: 750, y: 50 },
    style: { background: "#3b82f6", color: "white", border: "2px solid #2563eb", borderRadius: "8px", padding: "16px", fontWeight: 600 },
  },
  {
    id: "4",
    type: "default",
    data: { label: "Marketing" },
    position: { x: 250, y: 200 },
    style: { background: "#3b82f6", color: "white", border: "2px solid #2563eb", borderRadius: "8px", padding: "16px", fontWeight: 600 },
  },
  {
    id: "5",
    type: "default",
    data: { label: "Sales" },
    position: { x: 500, y: 200 },
    style: { background: "#3b82f6", color: "white", border: "2px solid #2563eb", borderRadius: "8px", padding: "16px", fontWeight: 600 },
  },
  {
    id: "6",
    type: "default",
    data: { label: "Operations" },
    position: { x: 750, y: 200 },
    style: { background: "#3b82f6", color: "white", border: "2px solid #2563eb", borderRadius: "8px", padding: "16px", fontWeight: 600 },
  },
];

const initialEdges = [
  { id: "e1-2", source: "1", target: "2", animated: true, style: { stroke: "#3b82f6" } },
  { id: "e2-3", source: "2", target: "3", animated: true, style: { stroke: "#3b82f6" } },
  { id: "e1-4", source: "1", target: "4", animated: true, style: { stroke: "#3b82f6" } },
  { id: "e2-5", source: "2", target: "5", animated: true, style: { stroke: "#3b82f6" } },
  { id: "e3-6", source: "3", target: "6", animated: true, style: { stroke: "#3b82f6" } },
];

const teamData = {
  "1": {
    name: "Engineering",
    members: ["Alice Chen", "Bob Smith", "Carol Davis", "David Wong"],
    progress: 75,
    blockers: ["API rate limits", "Database migration pending"],
    issues: 3,
    completedTasks: 24,
    totalTasks: 32,
  },
  "2": {
    name: "Product",
    members: ["Emma Johnson", "Frank Miller", "Grace Lee"],
    progress: 60,
    blockers: ["User research incomplete", "Stakeholder approval needed"],
    issues: 5,
    completedTasks: 18,
    totalTasks: 30,
  },
  "3": {
    name: "Design",
    members: ["Henry Park", "Iris Taylor", "Jack Brown"],
    progress: 85,
    blockers: ["Design system updates"],
    issues: 1,
    completedTasks: 17,
    totalTasks: 20,
  },
  "4": {
    name: "Marketing",
    members: ["Karen White", "Leo Garcia", "Mia Rodriguez"],
    progress: 90,
    blockers: [],
    issues: 0,
    completedTasks: 27,
    totalTasks: 30,
  },
  "5": {
    name: "Sales",
    members: ["Nathan Green", "Olivia Martinez", "Paul Anderson"],
    progress: 50,
    blockers: ["Q4 pipeline review", "Contract approval delays"],
    issues: 6,
    completedTasks: 15,
    totalTasks: 30,
  },
  "6": {
    name: "Operations",
    members: ["Quinn Thomas", "Rachel Moore", "Sam Jackson"],
    progress: 70,
    blockers: ["Vendor delays", "Budget allocation pending"],
    issues: 4,
    completedTasks: 21,
    totalTasks: 30,
  },
};

export default function Organization() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [selectedTeam, setSelectedTeam] = useState(null);

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  const onNodeClick = useCallback((event, node) => {
    setSelectedTeam(teamData[node.id] || null);
  }, []);

  return (
    <div className="organization-container">
      <div className="organization-flow">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          fitView
        >
          <Background color="#374151" gap={16} />
          <Controls />
          <MiniMap nodeColor="#3b82f6" />
        </ReactFlow>
      </div>

      {selectedTeam && (
        <div className="team-details-panel">
          <div className="team-details-header">
            <h3>{selectedTeam.name}</h3>
            <button
              className="close-btn"
              onClick={() => setSelectedTeam(null)}
            >
              ×
            </button>
          </div>

          <div className="team-details-content">
            <div className="detail-section">
              <h4>Progress</h4>
              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${selectedTeam.progress}%` }}
                >
                  {selectedTeam.progress}%
                </div>
              </div>
              <p className="progress-text">
                {selectedTeam.completedTasks} / {selectedTeam.totalTasks} tasks completed
              </p>
            </div>

            <div className="detail-section">
              <h4>Team Members ({selectedTeam.members.length})</h4>
              <ul className="members-list">
                {selectedTeam.members.map((member, idx) => (
                  <li key={idx}>{member}</li>
                ))}
              </ul>
            </div>

            <div className="detail-section">
              <h4>Blockers ({selectedTeam.blockers.length})</h4>
              {selectedTeam.blockers.length > 0 ? (
                <ul className="blockers-list">
                  {selectedTeam.blockers.map((blocker, idx) => (
                    <li key={idx}>{blocker}</li>
                  ))}
                </ul>
              ) : (
                <p className="no-blockers">No blockers 🎉</p>
              )}
            </div>

            <div className="detail-section">
              <h4>Open Issues</h4>
              <div className="issues-count">
                {selectedTeam.issues} {selectedTeam.issues === 1 ? "issue" : "issues"}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
