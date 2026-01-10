// src/pages/Login.jsx
import { useState } from "react";
import { motion } from "framer-motion";
import { API_BASE_URL } from '../config';
import "./Auth.css";

export default function Login({ goSignup, goForgot, goDashboard }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!email || !password) {
      setStatus("Enter email and password.");
      return;
    }
    setLoading(true);
    setStatus("");
    try {
      console.log("Login: sending request", { apiBase: API_BASE_URL, email });
      const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const text = await res.text();
        console.error("Login failed", res.status, text);
        setStatus(`Invalid credentials (${res.status}).`);
        return;
      }

      // optional debug hit to /me
      try {
        const meRes = await fetch(`${API_BASE_URL}/api/me`, {
          credentials: "include",
        });
        if (meRes.ok) {
          const me = await meRes.json();
          console.log("Logged in as", me);
          setStatus(`Signed in as ${me.name || me.email}. Redirecting…`);
        } else {
          console.warn("Login succeeded but /me failed", meRes.status);
          setStatus("Signed in, but failed to load your profile. Redirecting…");
        }
      } catch (err) {
        console.warn("Error fetching /me after login", err);
      }

      // Let AppLayout re-run the /me + invite gate logic
      goDashboard();
    } catch (err) {
      console.error("Login error", err);
      setStatus("Login failed. See console.");
    } finally {
      setLoading(false);
    }
  };

  const onKey = (e) => {
    if (e.key === "Enter") submit();
  };

  const handleGoogleLogin = () => {
    window.location.href = `${API_BASE_URL}/api/auth/google/login`;
  };

  return (
    <div className="auth-container">
      <motion.div
        className="auth-card glass"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <h2 className="auth-title">Welcome Back</h2>
        <p className="auth-subtitle">Sign in to your workspace</p>

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
          {loading ? "Signing in..." : "Sign In"}
        </button>

        <div className="auth-or">or</div>

        <button
          className="auth-button auth-button-google"
          type="button"
          onClick={handleGoogleLogin}
        >
          Continue with Google
        </button>

        <p className="auth-link" onClick={goForgot}>
          Forgot password?
        </p>

        <p className="auth-footer">
          New here? <span onClick={goSignup}>Create an account</span>
        </p>
      </motion.div>
    </div>
  );
}
