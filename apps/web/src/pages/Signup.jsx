// src/pages/Signup.jsx
import { useState } from "react";
import { motion } from "framer-motion";
import { API_BASE_URL } from '../config';
import "./Auth.css";

export default function Signup({ goLogin, goDashboard }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  const roleOptions =
    (import.meta.env.VITE_ROLE_OPTIONS ||
      "Product,Engineering,Design,Data,Ops,Other")
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);

  const submit = async () => {
    if (!name || !email || !password) {
      setStatus("Fill name, email, and password.");
      return;
    }

    setLoading(true);
    setStatus("");
    try {
      console.log("Signup: sending request", { apiBase: API_BASE_URL, email });

      const payload = {
        email,
        password,
        name,
        role: role || null,
      };

      const res = await fetch(`${API_BASE_URL}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const text = await res.text();
        console.error("Signup failed", res.status, text);
        let message = `Signup failed (${res.status}).`;
        try {
          const data = JSON.parse(text);
          if (data?.detail) {
            // Handle FastAPI validation errors (array of objects)
            if (Array.isArray(data.detail)) {
              message = data.detail.map(err => err.msg || JSON.stringify(err)).join(', ');
            } else if (typeof data.detail === 'string') {
              message = data.detail;
            } else {
              message = JSON.stringify(data.detail);
            }
          }
        } catch {
          // ignore parse errors, keep default
        }
        setStatus(message);
      } else {
        setStatus("Account created. Redirecting…");
        // Let AppLayout /me check handle where they land (invite vs dashboard)
        goDashboard();
      }
    } catch (err) {
      console.error("Signup error", err);
      setStatus("Signup failed. See console.");
    } finally {
      setLoading(false);
    }
  };

  const onKey = (e) => {
    if (e.key === "Enter") submit();
  };

  const handleGoogleSignup = () => {
    // Same endpoint as login – backend will create user if needed
    window.location.href = `${API_BASE_URL}/api/auth/google/login`;
  };

  return (
    <div className="auth-container">
      <motion.div
        className="auth-card glass"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <h2 className="auth-title">Create Account</h2>
        <p className="auth-subtitle">Start your workspace</p>

        <input
          className="auth-input"
          placeholder="Full Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={onKey}
        />

        <select
          className="auth-input"
          value={role}
          onChange={(e) => setRole(e.target.value)}
        >
          <option value="">Role (optional)</option>
          {roleOptions.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>

        <input
          className="auth-input"
          placeholder="Email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={onKey}
        />
        <input
          className="auth-input"
          placeholder="Password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={onKey}
        />

        {status && <div className="auth-status">{status}</div>}

        <button className="auth-button" onClick={submit} disabled={loading}>
          {loading ? "Signing up..." : "Sign Up"}
        </button>

        <div className="auth-or">or</div>

        <button
          className="auth-button auth-button-google"
          type="button"
          onClick={handleGoogleSignup}
        >
          Continue with Google
        </button>

        <p className="auth-footer">
          Already have an account? <span onClick={goLogin}>Sign in</span>
        </p>
      </motion.div>
    </div>
  );
}
