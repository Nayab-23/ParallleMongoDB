// src/pages/LandingPage.jsx
import { useState, useEffect, useMemo } from "react";
import "./LandingPage.css";
import { API_BASE_URL } from "../config";

import yugImg from "../assets/yug-parallel.png";
import seanImg from "../assets/sean-parallel.png";
import severinImg from "../assets/severin-parallel.png";
import nayabImg from "../assets/nayab-parallel.png";
import logoImg from "../assets/parallel-logo.png";
import MissionGlobeChat from "../components/MissionGlobeChat";
import linkedinIcon from "../../linkedin.png";

function scrollToSection(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth" });
}

export default function LandingPage() {
  const [cName, setCName] = useState("");
  const [cEmail, setCEmail] = useState("");
  const [cCompany, setCCompany] = useState("");
  const [cTeamSize, setCTeamSize] = useState("");
  const [cRole, setCRole] = useState("");
  const [cMessage, setCMessage] = useState("");
  const [submitStatus, setSubmitStatus] = useState(""); // "success" | "error" | ""

  /* ======================================================
     🔥 ADVANCED TYPING ANIMATION — LONG PHRASE LIST
  ====================================================== */
  const phrases = useMemo(
    () => [
      "AI boosts clarity",
      "AI accelerates teamwork",
      "Parallel simplifies work",
      "Parallel enhances focus",
      "Parallel unifies workflow",
      "AI removes friction",
      "Teams move faster",
      "Parallel amplifies output",
      "AI sharpens execution",
      "Clarity powers progress",
      "Parallel aligns teams",
      "AI automates context",
      "Work becomes effortless",
      "Everything stays in sync",
      "Parallel boosts momentum",
      "AI strengthens decisions",
      "Parallel reduces meetings",
      "Parallel brings awareness",
      "Alignment drives speed",
      "Parallel powers productivity"
    ],
    []
  );

  const [text, setText] = useState("");
  const [index, setIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const current = phrases[index % phrases.length];
    const speed = isDeleting ? 50 : 90;

    const t = setTimeout(() => {
      setText((prev) =>
        isDeleting
          ? current.substring(0, prev.length - 1)
          : current.substring(0, prev.length + 1)
      );

      if (!isDeleting && text === current) {
        setTimeout(() => setIsDeleting(true), 1000);
      }
      if (isDeleting && text === "") {
        setIsDeleting(false);
        setIndex((prev) => prev + 1);
      }
    }, speed);

    return () => clearTimeout(t);
  }, [text, isDeleting, index, phrases]);

  /* ======================================================
     WAITLIST HANDLER - SENDS TO BACKEND
  ====================================================== */
  const handleWaitlistSubmit = async (e) => {
    e.preventDefault();
    setSubmitStatus("submitting");

    const waitlistData = {
      name: cName,
      email: cEmail,
      company: cCompany,
      teamSize: cTeamSize,
      role: cRole,
      problems: cMessage,
    };

    try {
      const response = await fetch(`${API_BASE_URL}/api/waitlist`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(waitlistData)
      });

      const data = await response.json();

      if (response.ok) {
        setSubmitStatus("success");

        // Clear form after successful submission
        setTimeout(() => {
          setCName("");
          setCEmail("");
          setCCompany("");
          setCTeamSize("");
          setCRole("");
          setCMessage("");
          setSubmitStatus("");
        }, 2000);
      } else {
        console.error("Waitlist submission failed:", data);
        setSubmitStatus("error");
      }

    } catch (error) {
      console.error("Waitlist submission error:", error);
      setSubmitStatus("error");
    }
  };

  return (
    <>
      {/* NAVBAR */}
      <header className="navbar">
        <div className="logo">
          <img src={logoImg} className="nav-logo" alt="Parallel Logo" />
        </div>

        <nav className="nav-links">
          <button type="button" onClick={() => scrollToSection("mission")}>Mission</button>
          <button type="button" onClick={() => scrollToSection("product")}>Product</button>
          <button type="button" onClick={() => scrollToSection("team")}>Team</button>
          <a href="/app" className="nav-cta">Launch App</a>
        </nav>
      </header>

      {/* HERO */}
      <section className="hero">
        <div className="hero-inner">
          <h1>
            The Future of Team Intelligence
            <br />
            Built for Real-Time Collaboration
          </h1>

          {/* ⭐ NEW TYPING ANIMATION */}
          <p className="hero-typing">
            {text}
            <span className="cursor">|</span>
          </p>

          <p className="hero-subtitle">
            Parallel AI gives teams a shared awareness layer by streaming each
            teammate's AI workflow in real time — enabling unmatched speed and
            alignment.
          </p>

          <div className="hero-actions">
            <button className="btn-primary" onClick={() => scrollToSection("request-access")}>
              Become a Founding Partner
            </button>
            <button className="btn-secondary" onClick={() => scrollToSection("product")}>
              See Features
            </button>
          </div>

          {/* Social Proof Badge */}
          <div className="hero-badge">
            🏆 2nd Place at Berkeley AI Hackathon (60 teams)
          </div>
        </div>
      </section>

      {/* MISSION + PRODUCT */}
      <section className="section mission-product" id="mission">
        <div className="mission-product-left" id="product">
          <h2>What We Built</h2>
          <div className="product-grid">
            <div className="product-card">
              <h3>One Agent Per Teammate</h3>
              <p>Each person gets a representative agent that tracks their work.</p>
            </div>
            <div className="product-card">
              <h3>Live Awareness Layer</h3>
              <p>See real-time updates across tools in one unified place.</p>
            </div>
            <div className="product-card">
              <h3>Manager-Ready Briefings</h3>
              <p>AI-generated briefs so leaders stay aligned effortlessly.</p>
            </div>
            <div className="product-card">
              <h3>Unified Awareness</h3>
              <p>Your entire team stays in sync — instantly.</p>
            </div>
          </div>
        </div>

        <div className="mission-product-right">
          <MissionGlobeChat />
        </div>
      </section>

      {/* USE CASES - NEW SECTION */}
      <section className="section" id="use-cases">
        <h2>Real Problems We Solve</h2>
        <p style={{ marginBottom: "32px" }}>
          Built for 10-50 person teams that are scaling fast
        </p>
        <div className="use-cases-grid">
          <div className="use-case-card">
            <div className="use-case-icon">🚫</div>
            <h3>Never miss a blocked teammate</h3>
            <p>Know instantly when someone's stuck, before it costs you days</p>
          </div>
          <div className="use-case-card">
            <div className="use-case-icon">👁️</div>
            <h3>See what everyone's working on</h3>
            <p>Without endless status meetings or Slack interruptions</p>
          </div>
          <div className="use-case-card">
            <div className="use-case-icon">⚡</div>
            <h3>Catch miscommunication early</h3>
            <p>AI surfaces conflicts in priorities before they become emergencies</p>
          </div>
          <div className="use-case-card">
            <div className="use-case-icon">🎯</div>
            <h3>Stay aligned across time zones</h3>
            <p>Async-first awareness that keeps distributed teams moving</p>
          </div>
        </div>
      </section>

      {/* TEAM */}
      <section className="section" id="team">
        <h2>Meet the Team</h2>
        <p style={{ marginBottom: "24px", color: "#6b7280" }}>
          Four engineers building the future of team coordination
        </p>

        <div className="team-grid">
          <div className="team-card">
            <img src={seanImg} className="team-img" alt="Sean" />
            <h3>Sean Aminov</h3>
            <a
              href="https://www.linkedin.com/in/sean-aminov/"
              target="_blank"
              rel="noopener noreferrer"
              className="team-link"
              aria-label="Sean LinkedIn"
            >
              <img src={linkedinIcon} alt="LinkedIn" className="team-link-icon" />
            </a>
          </div>

          <div className="team-card">
            <img src={nayabImg} className="team-img" alt="Nayab" />
            <h3>Nayab Hossain</h3>
            <a
              href="https://www.linkedin.com/in/nayabhossain/"
              target="_blank"
              rel="noopener noreferrer"
              className="team-link"
              aria-label="Nayab LinkedIn"
            >
              <img src={linkedinIcon} alt="LinkedIn" className="team-link-icon" />
            </a>
          </div>

          <div className="team-card">
            <img src={yugImg} className="team-img" alt="Yug" />
            <h3>Yug More</h3>
            <a
              href="https://www.linkedin.com/in/yugmore13/"
              target="_blank"
              rel="noopener noreferrer"
              className="team-link"
              aria-label="Yug LinkedIn"
            >
              <img src={linkedinIcon} alt="LinkedIn" className="team-link-icon" />
            </a>
          </div>

          <div className="team-card">
            <img src={severinImg} className="team-img" alt="Severin" />
            <h3>Severin Spagnola</h3>
            <a
              href="https://www.linkedin.com/in/severin-spagnola-698a39396/"
              target="_blank"
              rel="noopener noreferrer"
              className="team-link"
              aria-label="Severin LinkedIn"
            >
              <img src={linkedinIcon} alt="LinkedIn" className="team-link-icon" />
            </a>
          </div>
        </div>
      </section>

      {/* PRICING - ENHANCED */}
      <section className="section" id="pricing">
        <h2>Founding Partner Pricing</h2>
        <p style={{ marginBottom: "32px", fontSize: "17px", color: "#4b5563" }}>
          Help shape the product. Lock in lifetime savings.
        </p>

        <div className="pricing-comparison">
          {/* Regular Pricing */}
          <div className="price-card price-card-regular">
            <div className="price-label">Regular Pricing</div>
            <h3>Standard Access</h3>
            <p className="price">$15-25k/year</p>
            <p className="price-subtext">Starting Q2 2025</p>
            <ul className="price-features">
              <li>Full platform access</li>
              <li>Standard support</li>
              <li>Standard SLA</li>
            </ul>
          </div>

          {/* Founding Partner Pricing */}
          <div className="price-card price-card-founding">
            <div className="price-badge">LIMITED SPOTS</div>
            <h3>Founding Partner</h3>
            <p className="price">$10,000/year</p>
            <div className="savings-badge">Save $5-15k every year, forever</div>
            
            <ul className="price-features">
              <li><strong>Lifetime 50% discount</strong></li>
              <li>All features included</li>
              <li>Direct line to founders</li>
              <li>Priority feature requests</li>
              <li>Help design the product</li>
              <li>Early access to new features</li>
            </ul>

            <button 
              className="btn-primary" 
              onClick={() => scrollToSection("request-access")}
            >
              Apply for Founding Partner
            </button>

            <p className="partner-note">
              <strong>Only 10 spots available.</strong> Your feedback directly shapes Parallel's roadmap.
            </p>
          </div>
        </div>

        <div className="pricing-footer">
          <p>
            🎯 Perfect for 10-50 person teams serious about coordination • 
            ⚡ Launch your pilot in January 2025
          </p>
        </div>
      </section>

      {/* REQUEST ACCESS - ENHANCED FORM */}
      <section className="section request-access" id="request-access">
        <h2>Become a Founding Partner</h2>
        <p className="request-access-subtitle">
          Join 10 pioneering teams building the future of work
        </p>

        <form className="request-form" onSubmit={handleWaitlistSubmit}>
          <div className="request-row">
            <input
              className="auth-input"
              type="text"
              placeholder="Your name *"
              value={cName}
              onChange={(e) => setCName(e.target.value)}
              required
            />
            <input
              className="auth-input"
              type="email"
              placeholder="Work email *"
              value={cEmail}
              onChange={(e) => setCEmail(e.target.value)}
              required
            />
          </div>

          <div className="request-row">
            <input
              className="auth-input"
              type="text"
              placeholder="Company name *"
              value={cCompany}
              onChange={(e) => setCCompany(e.target.value)}
              required
            />
            <select
              className="auth-input"
              value={cTeamSize}
              onChange={(e) => setCTeamSize(e.target.value)}
              required
            >
              <option value="">Team size *</option>
              <option value="1-10">1-10 people</option>
              <option value="10-25">10-25 people</option>
              <option value="25-50">25-50 people</option>
              <option value="50+">50+ people</option>
            </select>
          </div>

          <input
            className="auth-input"
            type="text"
            placeholder="Your role (e.g., CEO, VP Ops, Engineering Lead)"
            value={cRole}
            onChange={(e) => setCRole(e.target.value)}
          />

          <textarea
            className="auth-input request-message"
            placeholder="What coordination problems is your team facing? (Be specific - this helps us prioritize features) *"
            value={cMessage}
            onChange={(e) => setCMessage(e.target.value)}
            required
          />

          <button
            type="submit"
            className="btn-primary btn-submit"
            disabled={submitStatus === "submitting"}
          >
            {submitStatus === "submitting" ? "Submitting..." :
             submitStatus === "success" ? "✓ Submitted!" :
             "Submit Application"}
          </button>

          {submitStatus === "error" && (
            <p className="submit-error">
              Something went wrong. Please try again or email us at founder@parallelos.ai
            </p>
          )}

          {submitStatus === "success" && (
            <p className="submit-success">
              Thanks! We'll reach out within 48 hours.
            </p>
          )}
        </form>

        <div className="founding-partner-benefits">
          <h3>As a Founding Partner, you get:</h3>
          <div className="benefits-grid">
            <div className="benefit-item">
              <span className="benefit-icon">💬</span>
              <p><strong>Direct founder access</strong> via dedicated Slack channel</p>
            </div>
            <div className="benefit-item">
              <span className="benefit-icon">🎨</span>
              <p><strong>Co-create features</strong> — your feedback shapes the roadmap</p>
            </div>
            <div className="benefit-item">
              <span className="benefit-icon">💰</span>
              <p><strong>Lifetime 50% savings</strong> — locked in forever</p>
            </div>
            <div className="benefit-item">
              <span className="benefit-icon">⚡</span>
              <p><strong>Early access</strong> to all new capabilities</p>
            </div>
          </div>
        </div>

        <p className="request-note">
          Prefer to talk first?{" "}
          <a href="mailto:founder@parallelos.ai">founder@parallelos.ai</a>
        </p>
      </section>

      {/* FOOTER */}
      <footer>
        <p>© 2025 Parallel AI • Built with clarity & purpose.</p>
      </footer>
    </>
  );
}