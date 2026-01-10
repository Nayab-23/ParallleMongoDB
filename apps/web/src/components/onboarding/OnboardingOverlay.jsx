import { useCallback, useEffect, useState } from "react";
import "./OnboardingOverlay.css";
import { API_BASE_URL } from "../../config";

export default function OnboardingOverlay({ onComplete, onSkip }) {
  const [step, setStep] = useState(1);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchOnboardingStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/onboarding/status`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to load onboarding status");
      const data = await res.json();
      setStatus(data);
      if (data.onboarding_complete) {
        onComplete?.();
      }
    } catch (err) {
      console.error("Failed to fetch onboarding status", err);
    } finally {
      setLoading(false);
    }
  }, [onComplete]);

  useEffect(() => {
    fetchOnboardingStatus();
  }, [fetchOnboardingStatus]);

  const markOnboardingComplete = async () => {
    try {
      await fetch(`${API_BASE_URL}/api/onboarding/complete`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      console.error("Failed to mark onboarding complete", err);
    } finally {
      onComplete?.();
    }
  };

  const handleGmailConnect = () => {
    window.location.href = `${API_BASE_URL}/api/auth/google/login?scope=gmail`;
  };

  const handleCalendarConnect = () => {
    window.location.href = `${API_BASE_URL}/api/auth/google/login?scope=calendar`;
  };

  const handleNext = () => {
    if (step < 3) {
      setStep((s) => s + 1);
    } else {
      markOnboardingComplete();
    }
  };

  if (loading || !status || status.onboarding_complete) {
    return null;
  }

  return (
    <div className="onboarding-overlay">
      <div className="onboarding-card">
        <div className="progress-dots">
          {[1, 2, 3].map((num) => (
            <div key={num} className={`dot ${num === step ? "dot-active" : ""}`} />
          ))}
        </div>

        {step === 1 && (
          <div className="step-content">
            <div className="step-icon">👋</div>
            <h2>Welcome to Parallel</h2>
            <p>
              Your AI Chief of Staff is ready to help you focus on what matters. Let&apos;s get
              you set up in 3 quick steps.
            </p>
          </div>
        )}

        {step === 2 && (
          <div className="step-content">
            <div className="step-icon">📧</div>
            <h2>Connect Gmail</h2>
            <p>Parallel will read your emails to create intelligent task recommendations.</p>
            {status?.gmail_connected ? (
              <div className="status-badge success">✓ Gmail Connected</div>
            ) : (
              <button className="connect-btn" onClick={handleGmailConnect}>
                Connect Gmail
              </button>
            )}
          </div>
        )}

        {step === 3 && (
          <div className="step-content">
            <div className="step-icon">📅</div>
            <h2>Connect Calendar</h2>
            <p>Sync your calendar so Parallel can prepare you for meetings and manage your day.</p>
            {status?.calendar_connected ? (
              <div className="status-badge success">✓ Calendar Connected</div>
            ) : (
              <button className="connect-btn" onClick={handleCalendarConnect}>
                Connect Calendar
              </button>
            )}
          </div>
        )}

        <div className="step-navigation">
          <button className="skip-btn" onClick={onSkip}>
            Skip for now
          </button>
          <button className="next-btn" onClick={handleNext}>
            {step === 3 ? "Get Started" : "Next"}
          </button>
        </div>
      </div>
    </div>
  );
}
