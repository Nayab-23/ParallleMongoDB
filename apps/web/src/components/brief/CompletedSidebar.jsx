import "./Brief.css";

export default function CompletedSidebar({ items = [], onUndo = () => {}, isOpen = false, onToggle = () => {} }) {
  return (
    <div className={`completed-sidebar ${isOpen ? "open" : ""}`}>
      <div className="sidebar-header" onClick={onToggle}>
        <h3>✓ Completed</h3>
        <span className="count">{items.length}</span>
      </div>

      {isOpen && (
        <div className="completed-list">
          {items.length === 0 ? (
            <p className="empty-state">No completed items yet</p>
          ) : (
            items.map((item, i) => (
              <div key={i} className="completed-item">
                <div className="item-title completed">{item.title || "Item"}</div>
                <button className="undo-btn" onClick={() => onUndo(item)}>
                  ↶ Undo
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
