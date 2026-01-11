import { useState } from "react";
import "./UserPicker.css";

export default function UserPicker({ onUserSelected }) {
  const [selecting, setSelecting] = useState(false);

  const selectUser = (user) => {
    if (selecting) return;
    setSelecting(true);
    localStorage.setItem("demo_user", user);
    onUserSelected(user);
  };

  return (
    <div className="user-picker">
      <div className="user-picker-card">
        <h1>Choose Your Demo User</h1>
        <p className="subtitle">
          This demo uses two fake users to simulate collaboration
        </p>
        <div className="user-buttons">
          <button
            className="user-btn alice"
            onClick={() => selectUser("alice")}
            disabled={selecting}
          >
            <div className="user-avatar">A</div>
            <div className="user-name">Alice</div>
          </button>
          <button
            className="user-btn bob"
            onClick={() => selectUser("bob")}
            disabled={selecting}
          >
            <div className="user-avatar">B</div>
            <div className="user-name">Bob</div>
          </button>
        </div>
      </div>
    </div>
  );
}
