import { useEffect, useRef, useState } from "react";
import "./Brief.css";

// export default function PersonalBrief({ data = {} }) {
//   return (
//     <div className="brief-grid">
//       <BriefSection title="Top Priorities" items={data.priorities} />
//       <BriefSection title="Unread Email Summary" items={data.unread_emails} />
//       <BriefSection title="Upcoming Meetings" items={data.upcoming_meetings || data.calendar} />
//       <BriefSection title="Mentions & Follow-ups" items={data.mentions} />
//       <BriefSection title="Suggested Next Actions" items={data.actions} />
//     </div>
//   );
// }

export default function PersonalBrief({
  data = {},
  onComplete = () => {},
  onDelete = () => {},
  completingItem = null,
  showApprovedBadge = false,
}) {
  useEffect(() => {
    // console.log("[PersonalBrief] Unread emails:", data?.unread_emails);
    // console.log("[PersonalBrief] Sample email with link:", data?.unread_emails?.[0]);
  }, [data]);

  return (
    <div className="brief-grid">
      <BriefSection title="Top Priorities" items={data.priorities} onComplete={onComplete} onDelete={onDelete} completingItem={completingItem} showApprovedBadge={showApprovedBadge} />
      <BriefSection title="Unread Email Summary" items={data.unread_emails} onComplete={onComplete} onDelete={onDelete} completingItem={completingItem} showApprovedBadge={showApprovedBadge} />
      <BriefSection 
        title="Upcoming Meetings" 
        items={data.upcoming_meetings || data.calendar || []}  // ✅ Fallback
        onComplete={onComplete}
        onDelete={onDelete}
        completingItem={completingItem}
        showApprovedBadge={showApprovedBadge}
      />
      <BriefSection title="Mentions & Follow-ups" items={data.mentions || []} onComplete={onComplete} onDelete={onDelete} completingItem={completingItem} showApprovedBadge={showApprovedBadge} />
      <BriefSection title="Suggested Next Actions" items={data.actions} onComplete={onComplete} onDelete={onDelete} completingItem={completingItem} showApprovedBadge={showApprovedBadge} />
    </div>
  );
}

const isSameItem = (a, b) => {
  if (!a || !b) return false;
  if (a.source_id && b.source_id && a.source_id === b.source_id) return true;
  return a.title === b.title && a.source_type === b.source_type;
};

function useLongPress(callback, ms = 800) {
  const [start, setStart] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    if (start) {
      timerRef.current = setTimeout(callback, ms);
    } else {
      clearTimeout(timerRef.current);
    }
    return () => clearTimeout(timerRef.current);
  }, [start, callback, ms]);

  return {
    onMouseDown: () => setStart(true),
    onMouseUp: () => setStart(false),
    onMouseLeave: () => setStart(false),
    onTouchStart: () => setStart(true),
    onTouchEnd: () => setStart(false),
  };
}

function BriefSection({ title, items, onComplete, onDelete, completingItem, showApprovedBadge }) {
  const list = Array.isArray(items) ? items : [];
  return (
    <div className="brief-card">
      <div className="brief-card-title">{title}</div>
      {list.length === 0 && <div className="brief-empty">No items.</div>}
      {list.map((item, idx) => (
        <BriefItem key={idx} item={item} onComplete={onComplete} onDelete={onDelete} isCompleting={isSameItem(item, completingItem)} showApprovedBadge={showApprovedBadge} />
      ))}
    </div>
  );
}

function BriefItem({ item = {}, onComplete = () => {}, onDelete = () => {}, isCompleting, showApprovedBadge = false }) {
  const getItemLink = (it) => it.link || it.source?.link || null;
  const link = getItemLink(item);
  const longPressProps = useLongPress(() => onComplete(item));

  const handleClick = () => {
    if (link) {
      window.open(link, "_blank");
    }
  };

  return (
    <div
      className={`brief-item ${link ? "clickable" : ""} ${isCompleting ? "completing" : ""}`}
      onClick={(e) => {
        if (e.target.closest(".delete-btn")) return;
        handleClick();
      }}
      style={{ cursor: link ? "pointer" : "default" }}
      {...longPressProps}
    >
      {isCompleting && <div className="completion-overlay" />}
      <button
        className="delete-btn"
        onClick={(e) => {
          e.stopPropagation();
          onDelete(item);
        }}
        title="Delete without completing"
      >
        ×
      </button>
      <div className="item-content">
        <div className="item-title">{item.title || item.subject || "Item"}</div>
        {item.detail && <div className="item-detail">{item.detail}</div>}
        {item.snippet && <div className="item-detail">{item.snippet}</div>}
        {item.deadline && <div className="item-deadline">⏰ {item.deadline}</div>}
        {showApprovedBadge && <span className="approved-badge">✓ Approved</span>}
      </div>
      {link && (
        <div className="item-action">
          {item.source_type === "email" || item.source?.type === "email" ? "📧" : "📅"}
        </div>
      )}
    </div>
  );
}
