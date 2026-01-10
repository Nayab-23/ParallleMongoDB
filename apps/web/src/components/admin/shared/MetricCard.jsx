import React from "react";

const MetricCard = ({ title, value, subtitle, icon, trend }) => {
  return (
    <div className="metric-card">
      <div className="metric-header">
        {icon && <span className="metric-icon">{icon}</span>}
        <h3 className="metric-title">{title}</h3>
      </div>
      <div className="metric-value">{value}</div>
      {subtitle && <div className="metric-subtitle">{subtitle}</div>}
      {typeof trend === "number" && (
        <div className={`metric-trend ${trend > 0 ? "positive" : trend < 0 ? "negative" : ""}`}>
          {trend > 0 ? "up" : trend < 0 ? "down" : "flat"} {Math.abs(trend)}%
        </div>
      )}
    </div>
  );
};

export default MetricCard;
