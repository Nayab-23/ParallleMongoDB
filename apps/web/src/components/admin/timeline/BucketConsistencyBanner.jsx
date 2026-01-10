import React, { useEffect } from "react";

/**
 * Bucket Consistency Banner
 *
 * Checks for bucket consistency issues in the timeline data:
 * - Missing daily_goals, weekly_focus, or monthly_objectives
 * - Empty buckets that should have data
 * - Bucket structure mismatches
 *
 * Expected backend structure:
 * current_timeline: {
 *   daily_goals: { urgent: [], normal: [] } OR array,
 *   weekly_focus: { urgent: [], normal: [] } OR array,
 *   monthly_objectives: { urgent: [], normal: [] } OR array,
 *   "1d": { urgent: [], normal: [] },
 *   "7d": { urgent: [], normal: [] },
 *   "28d": { urgent: [], normal: [] }
 * }
 */

const BucketConsistencyBanner = ({ timelineData }) => {
  const currentTimeline = timelineData?.current_timeline;

  useEffect(() => {
    // Log payload keys for debugging (dev-only)
    if (process.env.NODE_ENV === "development" && timelineData) {
      console.log("🔍 [Timeline Debug] Full payload keys:", Object.keys(timelineData));
      console.log("🔍 [Timeline Debug] current_timeline keys:", currentTimeline ? Object.keys(currentTimeline) : "missing");
      console.log("🔍 [Timeline Debug] current_timeline structure:", currentTimeline);
    }
  }, [timelineData, currentTimeline]);

  // If no timeline data, don't show banner
  if (!currentTimeline) {
    return (
      <div
        style={{
          padding: "12px 16px",
          background: "#fef3c7",
          border: "1px solid #f59e0b",
          borderRadius: "6px",
          color: "#92400e",
          marginBottom: "16px",
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: "4px" }}>⚠️ No timeline data received</div>
        <div style={{ fontSize: "13px" }}>
          The <code>current_timeline</code> field is missing from the backend response.
        </div>
      </div>
    );
  }

  // Check for bucket presence and structure
  const issues = [];

  // Check for daily_goals (or "1d")
  const dailyGoals = currentTimeline.daily_goals || currentTimeline["1d"];
  if (!dailyGoals) {
    issues.push({
      severity: "error",
      message: "daily_goals missing from payload",
      detail: "Backend serialization issue - daily_goals field is undefined or null.",
    });
  } else if (typeof dailyGoals !== "object") {
    issues.push({
      severity: "warning",
      message: "daily_goals has unexpected structure",
      detail: `Expected object with {urgent, normal}, got ${typeof dailyGoals}`,
    });
  }

  // Check for weekly_focus (or "7d")
  const weeklyFocus = currentTimeline.weekly_focus || currentTimeline["7d"];
  if (!weeklyFocus) {
    issues.push({
      severity: "warning",
      message: "weekly_focus missing from payload",
      detail: "Backend may not be including weekly_focus field.",
    });
  } else if (typeof weeklyFocus !== "object") {
    issues.push({
      severity: "warning",
      message: "weekly_focus has unexpected structure",
      detail: `Expected object with {urgent, normal}, got ${typeof weeklyFocus}`,
    });
  }

  // Check for monthly_objectives (or "28d")
  const monthlyObjectives = currentTimeline.monthly_objectives || currentTimeline["28d"];
  if (!monthlyObjectives) {
    issues.push({
      severity: "warning",
      message: "monthly_objectives missing from payload",
      detail: "Backend may not be including monthly_objectives field.",
    });
  } else if (typeof monthlyObjectives !== "object") {
    issues.push({
      severity: "warning",
      message: "monthly_objectives has unexpected structure",
      detail: `Expected object with {urgent, normal}, got ${typeof monthlyObjectives}`,
    });
  }

  // Check counts
  const getDualCount = (bucket) => {
    if (!bucket) return null;
    if (Array.isArray(bucket)) return bucket.length;
    if (bucket.urgent && bucket.normal) {
      return (bucket.urgent?.length || 0) + (bucket.normal?.length || 0);
    }
    return null;
  };

  const dailyCount = getDualCount(dailyGoals);
  const weeklyCount = getDualCount(weeklyFocus);
  const monthlyCount = getDualCount(monthlyObjectives);

  // If no issues, show success banner
  if (issues.length === 0) {
    return (
      <div
        style={{
          padding: "12px 16px",
          background: "#d1fae5",
          border: "1px solid #10b981",
          borderRadius: "6px",
          color: "#065f46",
          marginBottom: "16px",
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: "4px" }}>✅ Bucket Consistency Check Passed</div>
        <div style={{ fontSize: "13px" }}>
          Daily: {dailyCount !== null ? dailyCount : "?"} items | Weekly: {weeklyCount !== null ? weeklyCount : "?"} items | Monthly: {monthlyCount !== null ? monthlyCount : "?"} items
        </div>
      </div>
    );
  }

  // Show issues
  const hasErrors = issues.some((i) => i.severity === "error");

  return (
    <div
      style={{
        padding: "12px 16px",
        background: hasErrors ? "#fee2e2" : "#fef3c7",
        border: `1px solid ${hasErrors ? "#ef4444" : "#f59e0b"}`,
        borderRadius: "6px",
        color: hasErrors ? "#991b1b" : "#92400e",
        marginBottom: "16px",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: "8px" }}>
        {hasErrors ? "⚠️" : "⚠️"} Bucket Consistency Issues Detected
      </div>
      {issues.map((issue, idx) => (
        <div
          key={idx}
          style={{
            padding: "8px 10px",
            background: "rgba(255, 255, 255, 0.5)",
            borderRadius: "4px",
            marginBottom: idx < issues.length - 1 ? "6px" : 0,
          }}
        >
          <div style={{ fontSize: "13px", fontWeight: 600, marginBottom: "2px" }}>
            {issue.severity === "error" ? "🔴" : "🟡"} {issue.message}
          </div>
          <div style={{ fontSize: "12px", opacity: 0.9 }}>{issue.detail}</div>
        </div>
      ))}

      {/* Bucket counts if available */}
      {(dailyCount !== null || weeklyCount !== null || monthlyCount !== null) && (
        <div
          style={{
            marginTop: "10px",
            paddingTop: "10px",
            borderTop: "1px solid rgba(0,0,0,0.1)",
            fontSize: "12px",
          }}
        >
          <strong>Detected counts:</strong> Daily: {dailyCount !== null ? dailyCount : "N/A"} | Weekly:{" "}
          {weeklyCount !== null ? weeklyCount : "N/A"} | Monthly: {monthlyCount !== null ? monthlyCount : "N/A"}
        </div>
      )}
    </div>
  );
};

export default BucketConsistencyBanner;
