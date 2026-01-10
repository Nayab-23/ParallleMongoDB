import { useEffect, useRef, useState } from "react";

export default function MentionInput({
  value,
  onChange,
  placeholder = "Task title",
  className = "",
}) {
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [teammates, setTeammates] = useState([]);
  const [filtered, setFiltered] = useState([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const fetchTeammates = async () => {
      try {
        const res = await fetch("/api/team/members", {
          credentials: "include",
          headers: {
            Authorization: `Bearer ${localStorage.getItem("token") || ""}`,
          },
        });
        const data = await res.json();
        if (!cancelled) {
          setTeammates(data?.members || []);
        }
      } catch (err) {
        console.error("Error fetching teammates:", err);
      }
    };
    fetchTeammates();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChange = (e) => {
    const newValue = e.target.value;
    const cursorPos = e.target.selectionStart;
    onChange(newValue);

    const textBeforeCursor = newValue.slice(0, cursorPos);
    const lastAtIndex = textBeforeCursor.lastIndexOf("@");

    if (lastAtIndex !== -1 && cursorPos - lastAtIndex <= 20) {
      const searchTerm = textBeforeCursor.slice(lastAtIndex + 1).toLowerCase();
      const filteredTeammates = teammates.filter(
        (mate) =>
          mate.name?.toLowerCase().includes(searchTerm) ||
          mate.email?.toLowerCase().includes(searchTerm)
      );
      setFiltered(filteredTeammates);
      setShowSuggestions(filteredTeammates.length > 0);
      setSelectedIndex(0);
    } else {
      setShowSuggestions(false);
    }
  };

  const selectTeammate = (teammate) => {
    if (!inputRef.current) return;
    const cursorPos = inputRef.current.selectionStart;
    const textBeforeCursor = value.slice(0, cursorPos);
    const textAfterCursor = value.slice(cursorPos);
    const lastAtIndex = textBeforeCursor.lastIndexOf("@");
    if (lastAtIndex === -1) return;

    const newValue =
      value.slice(0, lastAtIndex) + `@${teammate.name} ` + textAfterCursor;

    onChange(newValue);
    setShowSuggestions(false);

    setTimeout(() => {
      inputRef.current?.focus();
      const newCursorPos = lastAtIndex + teammate.name.length + 2;
      inputRef.current?.setSelectionRange(newCursorPos, newCursorPos);
    }, 0);
  };

  const handleKeyDown = (e) => {
    if (!showSuggestions) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && filtered.length > 0) {
      e.preventDefault();
      selectTeammate(filtered[selectedIndex]);
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
    }
  };

  return (
    <div className="mention-input" style={{ position: "relative" }}>
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className={className}
        autoComplete="off"
      />

      {showSuggestions && (
        <div
          className="mention-suggestions"
          style={{
            position: "absolute",
            zIndex: 50,
            marginTop: 4,
            width: "100%",
            background: "var(--surface, #fff)",
            border: "1px solid var(--border, #e5e7eb)",
            borderRadius: 8,
            boxShadow: "0 10px 30px rgba(0,0,0,0.08)",
            maxHeight: 200,
            overflowY: "auto",
          }}
        >
          {filtered.map((mate, idx) => (
            <button
              key={mate.id || mate.email || mate.name}
              type="button"
              onClick={() => selectTeammate(mate)}
              style={{
                width: "100%",
                padding: "10px 12px",
                textAlign: "left",
                background:
                  idx === selectedIndex ? "rgba(59,130,246,0.12)" : "transparent",
                border: "none",
                cursor: "pointer",
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 14 }}>{mate.name}</div>
              <div style={{ fontSize: 12, color: "#6b7280" }}>{mate.email}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
