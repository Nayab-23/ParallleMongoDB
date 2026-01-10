import { API_BASE_URL } from "../config";
import { getNotifications as getV1Notifications } from "./notificationApi";

/**
 * Fetch all rooms for the organization
 * @returns {Promise<Array>} List of rooms
 */
export async function getRooms() {
  const response = await fetch(`${API_BASE_URL}/api/rooms`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch rooms: ${response.status}`);
  }

  return response.json();
}

/**
 * Fetch details for a specific room
 * @param {string} roomId - ID of the room
 * @returns {Promise<Object>} Room details
 */
export async function getRoom(roomId) {
  const response = await fetch(`${API_BASE_URL}/api/rooms/${roomId}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch room ${roomId}: ${response.status}`);
  }

  return response.json();
}

/**
 * Fetch members for a specific room
 * @param {string} roomId - ID of the room
 * @returns {Promise<Array>} List of room members
 */
export async function getRoomMembers(roomId) {
  const response = await fetch(`${API_BASE_URL}/api/rooms/${roomId}/members`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch room members: ${response.status}`);
  }

  return response.json();
}

/**
 * Fetch activity history with optional filtering
 * @param {Object} options - Query options
 * @param {string} options.roomId - Filter by room ID
 * @param {number} options.days - Number of days to fetch (default: 7)
 * @param {number} options.limit - Max number of activities (default: 50)
 * @returns {Promise<Array>} Activity history
 */
export async function getActivityHistory({ roomId, days = 7, limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (roomId) params.append("room_id", roomId);
  params.append("days", days.toString());
  params.append("limit", limit.toString());

  const response = await fetch(
    `${API_BASE_URL}/api/activity/history?${params}`,
    {
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch activity history: ${response.status}`);
  }

  return response.json();
}

/**
 * Fetch notifications with optional filtering
 * @param {Object} options - Query options
 * @param {string} options.roomId - Filter by room ID
 * @param {string} options.severity - Filter by severity (urgent, normal)
 * @param {boolean} options.unreadOnly - Only fetch unread notifications
 * @param {number} options.limit - Max number of notifications (default: 50)
 * @returns {Promise<Object>} Notification data
 */
export async function getNotifications({
  roomId,
  severity,
  unreadOnly = false,
  limit = 50,
} = {}) {
  const notifications = await getV1Notifications(!!unreadOnly, limit);

  let filtered = notifications;
  if (roomId) {
    filtered = filtered.filter(
      (n) =>
        n?.room_id === roomId ||
        n?.roomId === roomId ||
        n?.data?.room_id === roomId ||
        n?.data?.roomId === roomId
    );
  }
  if (severity) {
    filtered = filtered.filter(
      (n) => n?.severity === severity || n?.data?.severity === severity
    );
  }

  return { notifications: filtered, total: filtered.length };
}

/**
 * Fetch room statistics (when backend endpoint is available)
 * @param {string} roomId - ID of the room
 * @returns {Promise<Object>} Room statistics
 */
export async function getRoomStats(roomId) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/rooms/${roomId}/stats`,
      {
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      }
    );

    if (!response.ok) {
      // If endpoint doesn't exist yet, return null
      if (response.status === 404) return null;
      throw new Error(`Failed to fetch room stats: ${response.status}`);
    }

    return response.json();
  } catch (err) {
    console.warn(`Room stats endpoint not available: ${err.message}`);
    return null;
  }
}

/**
 * Fetch AI-generated room summary (when backend endpoint is available)
 * @param {string} roomId - ID of the room
 * @returns {Promise<string|null>} Room summary or null if unavailable
 */
export async function getRoomSummary(roomId) {
  try {
    const response = await fetch(
      `${API_BASE_URL}/api/rooms/${roomId}/summary`,
      {
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
      }
    );

    if (!response.ok) {
      // If endpoint doesn't exist yet, return null
      if (response.status === 404) return null;
      throw new Error(`Failed to fetch room summary: ${response.status}`);
    }

    const data = await response.json();
    return data?.summary || null;
  } catch (err) {
    console.warn(`Room summary endpoint not available: ${err.message}`);
    return null;
  }
}

/**
 * Fetch complete organization graph data (when backend endpoint is available)
 * This is an optimized endpoint that returns pre-calculated data for all rooms
 * @returns {Promise<Object|null>} Graph data with rooms and edges
 */
export async function getOrgGraphData() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/org/graph-data`, {
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      // If endpoint doesn't exist yet, return null
      if (response.status === 404) return null;
      throw new Error(`Failed to fetch org graph data: ${response.status}`);
    }

    return response.json();
  } catch (err) {
    console.warn(`Org graph data endpoint not available: ${err.message}`);
    return null;
  }
}
