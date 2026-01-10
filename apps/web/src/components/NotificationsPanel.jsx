import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getNotifications as apiGetNotifications,
  markNotificationRead,
} from "../api/notificationApi";
import "./NotificationsPanel.css";

const parseTimestamp = (value) => {
  if (!value) return 0;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 0;
  return date.getTime();
};

function getNotificationIcon(type) {
  switch (type) {
    case "conflict_semantic":
    case "conflict_file":
      return "⚠️";
    case "reminder":
    case "meeting_reminder":
      return "📅";
    case "mention":
      return "💬";
    case "team_update":
      return "🔔";
    case "task_assigned":
      return "✅";
    default:
      return "📬";
  }
}

function getNotificationColor(type) {
  switch (type) {
    case "conflict_semantic":
    case "conflict_file":
      return "#fee2e2";
    case "reminder":
    case "meeting_reminder":
      return "#fef3c7";
    case "mention":
      return "#dbeafe";
    case "team_update":
      return "#e0e7ff";
    case "task_assigned":
      return "#d1fae5";
    default:
      return "#f3f4f6";
  }
}

function formatTitle(notif, currentUserName) {
  const fromUser = notif.data?.from_user || notif.data?.actor_name || notif.from_user;
  const sourceType = notif.type || notif.data?.source_type;
  switch (notif.type) {
    case "conflict_semantic":
    case "conflict_file":
      return "⚠️ Conflict detected";
    case "reminder":
    case "meeting_reminder":
      if (fromUser && fromUser === currentUserName) {
        return "📅 Reminder";
      }
      return fromUser ? `✅ ${fromUser} assigned you a task` : "📅 Reminder";
    case "mention":
      return fromUser ? `💬 ${fromUser} mentioned you` : "💬 You were mentioned";
    case "team_update":
      return fromUser ? `🔔 ${fromUser} - Team Update` : "🔔 Team Update";
    case "task_assigned":
      if (fromUser && fromUser === currentUserName) {
        return "📅 Reminder";
      }
      return fromUser ? `✅ ${fromUser} assigned you` : "✅ Task Assigned";
    default:
      return notif.title || "Notification";
  }
}

function formatBody(notif, currentUserName) {
  const fromUser = notif.data?.from_user || notif.data?.actor_name || notif.from_user;
  const relatedUser = notif.data?.related_user_id ? `User ${notif.data.related_user_id}` : "A teammate";
  const rawMessage =
    (typeof notif.message === "string" && notif.message) ||
    (typeof notif.body === "string" && notif.body) ||
    notif.data?.task_title ||
    notif.data?.task ||
    "";
  let cleanMessage = rawMessage;
  cleanMessage = cleanMessage.replace(/@[\w\s]+assigned you:\s*/i, "");
  cleanMessage = cleanMessage.replace(/^Reminder:\s*/i, "");
  if (fromUser && fromUser === currentUserName && notif.type === "reminder") {
    return cleanMessage;
  }
  if (notif.type === "conflict_semantic" || notif.type === "conflict_file") {
    return `${relatedUser} is editing a similar item. ${cleanMessage}`;
  }
  return cleanMessage;
}

function formatRelativeTime(timestamp) {
  if (!timestamp) return "";
  const now = new Date();
  const then = new Date(timestamp);
  if (Number.isNaN(then.getTime())) return "";
  const diffMs = now - then;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function groupNotificationsByDate(list) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const groups = {
    today: [],
    yesterday: [],
    older: [],
  };

  list.forEach((notif) => {
    const ts = notif.created_at || notif.timestamp || notif.createdAt;
    const date = ts ? new Date(ts) : null;
    if (!date || Number.isNaN(date.getTime())) {
      groups.older.push(notif);
      return;
    }
    date.setHours(0, 0, 0, 0);
    if (date.getTime() === today.getTime()) {
      groups.today.push(notif);
    } else if (date.getTime() === yesterday.getTime()) {
      groups.yesterday.push(notif);
    } else {
      groups.older.push(notif);
    }
  });

  return groups;
}

function NotificationCard({ notification, onMarkRead, currentUserName }) {
  const type = notification.type || notification.notification_type || "notification";
  const isRead = notification.is_read ?? notification.read ?? false;
  const icon = getNotificationIcon(type);
  const color = getNotificationColor(type);
  const title = formatTitle({ ...notification, type }, currentUserName);
  const body = formatBody({ ...notification, type }, currentUserName);
  const createdAt = notification.created_at || notification.timestamp;
  const room = notification.data?.room || notification.data?.room_name || notification.room;
  const notificationId = notification.id || notification.notification_id;
  const isConflict = type === "conflict_semantic" || type === "conflict_file";

  return (
    <div className={`notification-card ${isRead ? "read" : "unread"}`}>
      <div className="notification-icon" style={{ background: color }}>
        {icon}
      </div>
        <div className="notification-content">
          <div className="notification-title">{title}</div>
          <div className="notification-body">{body}</div>
          <div className="notification-meta">
            {isConflict && <span className="notification-badge">Conflict</span>}
            <span className="notification-time">
              {formatRelativeTime(createdAt)}
            </span>
            {room && <span className="notification-room">{room}</span>}
          </div>
        </div>
      {!isRead && notificationId && (
        <button
          className="notification-mark-read"
          onClick={() => onMarkRead(notificationId)}
          type="button"
          aria-label="Mark notification as read"
        >
          ✓
        </button>
      )}
    </div>
  );
}

export default function NotificationsPanel({ user = null }) {
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [conflictsOnly, setConflictsOnly] = useState(false);

  const fetchNotifications = useCallback(async () => {
    try {
      const list = await apiGetNotifications(false, 50);
      setNotifications(list);
    } catch (err) {
      console.error("Error fetching notifications:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 30000);
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  const markAsRead = async (id) => {
    try {
      await markNotificationRead(id);
      setNotifications((prev) =>
        prev.map((n) =>
          n.id === id || n.notification_id === id
            ? { ...n, read: true, is_read: true }
            : n
        )
      );
    } catch (err) {
      console.error("Error marking notification read:", err);
    }
  };

  const sortedNotifications = useMemo(() => {
    const list = Array.isArray(notifications) ? notifications : [];
    return [...list].sort(
      (a, b) =>
        parseTimestamp(b.created_at || b.timestamp || b.createdAt) -
        parseTimestamp(a.created_at || a.timestamp || a.createdAt)
    );
  }, [notifications]);

  const grouped = useMemo(
    () => {
      const base = conflictsOnly
        ? sortedNotifications.filter(
            (n) => n.type === "conflict_semantic" || n.type === "conflict_file"
          )
        : sortedNotifications;
      return groupNotificationsByDate(base);
    },
    [sortedNotifications, conflictsOnly]
  );

  const currentUserName = user?.name || user?.email || null;
  const hasNotifications =
    grouped.today.length + grouped.yesterday.length + grouped.older.length > 0;

  if (loading && notifications.length === 0) {
    return (
      <div className="notifications-panel notifications-view">
        <div className="notifications-loading">Loading notifications…</div>
      </div>
    );
  }

  return (
    <div className="notifications-panel notifications-view">
      <div className="notifications-header">
        <h2>Notifications</h2>
        <label className="conflict-toggle">
          <input
            type="checkbox"
            checked={conflictsOnly}
            onChange={(e) => setConflictsOnly(e.target.checked)}
          />
          Conflicts only
        </label>
      </div>
      <div className="notifications-container">
        {!hasNotifications ? (
          <div className="notifications-empty">No notifications</div>
        ) : (
          <>
            {grouped.today.length > 0 && (
              <div className="notification-group">
                <div className="notification-group-header">Today</div>
                {grouped.today.map((notif) => (
                  <NotificationCard
                    key={notif.id || notif.notification_id || notif.created_at}
                    notification={notif}
                    onMarkRead={markAsRead}
                    currentUserName={currentUserName}
                  />
                ))}
              </div>
            )}
            {grouped.yesterday.length > 0 && (
              <div className="notification-group">
                <div className="notification-group-header">Yesterday</div>
                {grouped.yesterday.map((notif) => (
                  <NotificationCard
                    key={notif.id || notif.notification_id || notif.created_at}
                    notification={notif}
                    onMarkRead={markAsRead}
                    currentUserName={currentUserName}
                  />
                ))}
              </div>
            )}
            {grouped.older.length > 0 && (
              <div className="notification-group">
                <div className="notification-group-header">Earlier</div>
                {grouped.older.map((notif) => (
                  <NotificationCard
                    key={notif.id || notif.notification_id || notif.created_at}
                    notification={notif}
                    onMarkRead={markAsRead}
                    currentUserName={currentUserName}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
