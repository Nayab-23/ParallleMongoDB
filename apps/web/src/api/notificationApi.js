import { API_BASE_URL } from "../config";

export async function getNotifications(unreadOnly = false, limit = 50) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/notifications?unread_only=${unreadOnly}&limit=${limit}`,
    { credentials: "include" }
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch notifications: ${response.status}`);
  }

  const data = await response.json();
  return Array.isArray(data?.notifications) ? data.notifications : Array.isArray(data) ? data : [];
}

export async function getUnreadCount() {
  const response = await fetch(`${API_BASE_URL}/api/v1/notifications/unread-count`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch unread count: ${response.status}`);
  }
  const data = await response.json();
  return typeof data?.count === "number" ? data.count : 0;
}

export async function markNotificationRead(notificationId) {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/notifications/${notificationId}/read`,
    {
      method: "PATCH",
      credentials: "include",
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to mark notification as read: ${response.status}`);
  }

  return response.json();
}

export async function markAllNotificationsRead() {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/notifications/mark-all-read`,
    {
      method: "PATCH",
      credentials: "include",
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to mark all notifications as read: ${response.status}`);
  }

  return response.json();
}

/**
 * Get notification summary for LLM context
 * Groups notifications by type and urgency
 * @returns {Promise<Object>} Summarized notification data
 */
export async function getNotificationSummary() {
  const notifications = await getNotifications(true, 100);
  const total = notifications.length;

  // Urgent if: severity='urgent' OR type contains 'conflict'
  const urgentCount = notifications.filter(
    (n) =>
      n?.severity === "urgent" ||
      n?.data?.severity === "urgent" ||
      n?.type?.includes("conflict")
  ).length;

  const byType = notifications.reduce((acc, notif) => {
    const type = notif.type || "general";
    if (!acc[type]) acc[type] = [];
    acc[type].push(notif);
    return acc;
  }, {});

  return {
    total,
    urgentCount,
    notifications,
    byType,
  };
}
