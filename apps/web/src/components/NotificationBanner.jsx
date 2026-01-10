import { useState, useEffect, useCallback } from "react";
import "./NotificationBanner.css";
import {
  getNotificationSummary,
  markAllNotificationsRead,
} from "../api/notificationApi";

export default function NotificationBanner({ user, onRequestSummary }) {
  const [notificationData, setNotificationData] = useState(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchNotifications = useCallback(async () => {
    if (!user?.id) return;

    try {
      setLoading(true);
      setError(null);
      const data = await getNotificationSummary();
      setNotificationData(data);
    } catch (err) {
      console.error("[NotificationBanner] Failed to fetch:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => {
    fetchNotifications();

    // Poll for new notifications every 30 seconds
    const interval = setInterval(fetchNotifications, 30000);
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  const handleClick = () => {
    if (!notificationData || notificationData.total === 0) return;

    setIsExpanded(!isExpanded);

    // If expanding, request LLM summary
    if (!isExpanded && onRequestSummary) {
      onRequestSummary(notificationData);
    }
  };

  const handleDismissAll = async (e) => {
    e.stopPropagation();

    try {
      await markAllNotificationsRead();
      setNotificationData({ total: 0, urgentCount: 0, notifications: [], byType: {} });
      setIsExpanded(false);
    } catch (err) {
      console.error("[NotificationBanner] Failed to mark all as read:", err);
    }
  };

  // Don't show if no notifications
  if (loading || error || !notificationData || notificationData.total === 0) {
    return null;
  }

  const { total, urgentCount } = notificationData;
  const hasConflict = Array.isArray(notificationData.notifications)
    ? notificationData.notifications.some(
        (n) => n.type === "conflict_semantic" || n.type === "conflict_file"
      )
    : false;

  return (
    <div className="notification-banner-container">
      <div
        className={`notification-banner ${isExpanded ? "expanded" : ""}`}
        onClick={handleClick}
      >
        <div className="notification-badges">
          {/* Total notifications badge */}
          <div className="notification-badge notification-badge-normal">
            <span className="notification-icon">🔔</span>
            <span className="notification-count">
              {total} {total === 1 ? "notification" : "notifications"}
            </span>
          </div>

          {/* Urgent notifications badge (only show if there are urgent ones) */}
          {urgentCount > 0 && (
            <div className="notification-badge notification-badge-urgent">
              <span className="notification-icon">⚠️</span>
              <span className="notification-count">
                {urgentCount} urgent
              </span>
            </div>
          )}
          {hasConflict && (
            <div className="notification-badge notification-badge-urgent">
              <span className="notification-icon">🧠</span>
              <span className="notification-count">Conflicts detected</span>
            </div>
          )}
        </div>

        <div className="notification-action">
          <span className="notification-action-text">
            Click to see summary →
          </span>
        </div>

        {/* Dismiss button */}
        <button
          type="button"
          className="notification-dismiss-btn"
          onClick={handleDismissAll}
          aria-label="Dismiss all notifications"
        >
          ✕
        </button>
      </div>

      {/* Expanded state - shows brief preview */}
      {isExpanded && (
        <div className="notification-preview">
          <div className="notification-preview-header">
            <strong>Recent Notifications</strong>
          </div>
          <div className="notification-preview-list">
            {notificationData.notifications.slice(0, 3).map((notif, idx) => (
              <div
                key={notif.id || idx}
                className={`notification-preview-item ${
                  notif.severity === "urgent" ||
                  notif.data?.severity === "urgent"
                    ? "urgent"
                    : ""
                }`}
              >
                <div className="notification-preview-title">
                  {notif.title || notif.type || "Notification"}
                </div>
                <div className="notification-preview-message">
                  {notif.message ||
                    notif.data?.summary ||
                    "No details available"}
                </div>
              </div>
            ))}
          </div>
          {notificationData.total > 3 && (
            <div className="notification-preview-more">
              and {notificationData.total - 3} more...
            </div>
          )}
          <div className="notification-preview-footer">
            <em>Ask me to explain any of these in detail!</em>
          </div>
        </div>
      )}
    </div>
  );
}
