import { useState, useMemo } from "react";

function renderValue(val) {
  if (val === null || val === undefined) return "—";
  if (typeof val === "string") return val;
  if (typeof val === "number" || typeof val === "boolean") return String(val);
  if (Array.isArray(val)) {
    return val.map((item, idx) => (
      <li key={idx} className="context-item">
        {renderValue(item)}
      </li>
    ));
  }
  if (typeof val === "object") {
    return JSON.stringify(val, null, 2);
  }
  return String(val);
}

function SectionsRenderer({ sections }) {
  return (
    <div className="context-sections">
      {sections.map((section, idx) => (
        <div key={section.title || idx} className="context-section">
          {section.title && <div className="context-section-title">{section.title}</div>}
          {Array.isArray(section.items) && section.items.length > 0 ? (
            <ul className="context-section-list">
              {section.items.map((item, i) => (
                <li key={i} className="context-item">
                  {renderValue(item)}
                </li>
              ))}
            </ul>
          ) : (
            <div className="context-empty">No items</div>
          )}
        </div>
      ))}
    </div>
  );
}

function GenericRenderer({ preview }) {
  if (!preview || typeof preview !== "object") {
    return <div className="context-empty">No context preview available</div>;
  }

  const entries = Object.entries(preview).filter(
    ([, val]) => val !== null && val !== undefined
  );

  if (entries.length === 0) {
    return <div className="context-empty">No context preview available</div>;
  }

  return (
    <div className="context-sections">
      {entries.map(([key, val]) => (
        <div key={key} className="context-section">
          <div className="context-section-title">{key}</div>
          {Array.isArray(val) ? (
            <ul className="context-section-list">
              {val.map((item, idx) => (
                <li key={idx} className="context-item">
                  {renderValue(item)}
                </li>
              ))}
            </ul>
          ) : (
            <div className="context-item">{renderValue(val)}</div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function ContextUsedDrawer({
  preview,
  disabled = false,
  assistantMessages = [],
  selectedMessageId = null,
  onSelectMessage = () => {},
}) {
  const [open, setOpen] = useState(false);

  const content = useMemo(() => {
    if (preview?.sections && Array.isArray(preview.sections)) {
      return <SectionsRenderer sections={preview.sections} />;
    }
    return <GenericRenderer preview={preview} />;
  }, [preview]);

  return (
    <div className={`context-drawer ${open ? "open" : "closed"}`}>
      <button
        type="button"
        className="context-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        Context used {open ? "▾" : "▸"}
      </button>
      {open && (
        <div className="context-body">
          {disabled ? (
            <div className="context-empty">Preview disabled</div>
          ) : (
            <>
              {Array.isArray(assistantMessages) && assistantMessages.length > 1 && (
                <div className="context-select">
                  <label htmlFor="context-select">Select message:</label>
                  <select
                    id="context-select"
                    value={selectedMessageId || ""}
                    onChange={(e) => onSelectMessage(e.target.value || null)}
                  >
                    {assistantMessages.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.snippet}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {preview ? content : <div className="context-empty">No context preview available</div>}
              {preview?.sections && Array.isArray(preview.sections) && (
                <TeamActivitySection preview={preview} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function TeamActivitySection({ preview }) {
  if (!preview?.sections || !Array.isArray(preview.sections)) return null;
  const teamSection =
    preview.sections.find((s) =>
      typeof s.title === "string" && s.title.toLowerCase().includes("team")
    ) || preview.sections.find((s) =>
      typeof s.title === "string" && s.title.toLowerCase().includes("teammate")
    );
  if (!teamSection || !Array.isArray(teamSection.items) || teamSection.items.length === 0) {
    return null;
  }
  return (
    <div className="context-team">
      <div className="context-section-title">Team activity the agent used</div>
      <ul className="context-section-list">
        {teamSection.items.slice(0, 5).map((item, idx) => (
          <li key={idx} className="context-item">
            {renderValue(item)}
          </li>
        ))}
      </ul>
    </div>
  );
}
