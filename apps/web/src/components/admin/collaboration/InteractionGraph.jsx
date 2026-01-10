const InteractionGraph = ({ data }) => {
  if (!data || !data.nodes || !data.edges) {
    return <div className="text-gray-500">No interaction data to display</div>;
  }

  console.log('🤝 [ADMIN/InteractionGraph] Rendering graph with', data.nodes.length, 'nodes and', data.edges.length, 'edges');

  // Simple text-based visualization
  // (Can be replaced with react-force-graph later)
  return (
    <div className="interaction-graph-simple">
      <div className="graph-nodes">
        <h4>Users ({data.nodes.length})</h4>
        {data.nodes.map((node, index) => (
          <div key={index} className="graph-node">
            <span className="node-label">{node.label}</span>
            <span className="node-activity">{node.activity_count} interactions</span>
          </div>
        ))}
      </div>

      <div className="graph-edges">
        <h4>Connections ({data.edges.length})</h4>
        {data.edges.map((edge, index) => (
          <div key={index} className="graph-edge">
            <div className="edge-users">
              {edge.source} ↔ {edge.target}
            </div>
            <div className="edge-stats">
              <span className="edge-weight">Weight: {edge.weight}</span>
              <span className="edge-types">{edge.types.join(', ')}</span>
            </div>
            <div className="edge-breakdown">
              {edge.chat_count > 0 && <span>💬 {edge.chat_count}</span>}
              {edge.notification_count > 0 && <span>🔔 {edge.notification_count}</span>}
              {edge.conflict_count > 0 && <span>⚠️ {edge.conflict_count}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default InteractionGraph;
