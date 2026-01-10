/**
 * Utility functions for calculating organization graph metrics
 */

/**
 * Calculate room status based on notifications and activity
 * @param {Object} room - Room data
 * @param {Array} notifications - All notifications
 * @param {Array} activities - All activities
 * @returns {string} "Healthy" | "Strained" | "Critical"
 */
export function calculateRoomStatus(room, notifications, activities) {
  if (!room || !room.id) return "Healthy";

  // Count urgent notifications for this room
  const urgentCount = notifications.filter(
    (n) =>
      (n.room_id === room.id || n.data?.room_id === room.id) &&
      (n.severity === "urgent" || n.data?.severity === "urgent")
  ).length;

  // Check recent activity (last hour)
  const oneHourAgo = Date.now() - 3600000;
  const recentActivity = activities.filter((a) => {
    if (a.room_id !== room.id) return false;
    const timestamp = new Date(a.timestamp || a.created_at).getTime();
    return timestamp > oneHourAgo;
  }).length;

  // Critical: 5+ urgent notifications OR no activity in 24h
  const oneDayAgo = Date.now() - 86400000;
  const hasRecentActivity = activities.some((a) => {
    if (a.room_id !== room.id) return false;
    const timestamp = new Date(a.timestamp || a.created_at).getTime();
    return timestamp > oneDayAgo;
  });

  if (urgentCount >= 5 || !hasRecentActivity) return "Critical";

  // Strained: 2-4 urgent notifications
  if (urgentCount >= 2) return "Strained";

  // Healthy: <2 urgent, recent activity
  return "Healthy";
}

/**
 * Calculate fires (urgent notifications) count for a room
 * @param {string} roomId - Room ID
 * @param {Array} notifications - All notifications
 * @returns {number} Count of urgent unread notifications
 */
export function calculateFires(roomId, notifications) {
  return notifications.filter(
    (n) =>
      (n.room_id === roomId || n.data?.room_id === roomId) &&
      (n.severity === "urgent" || n.data?.severity === "urgent") &&
      !n.is_read
  ).length;
}

/**
 * Calculate overdue tasks count for a room
 * This is a simplified version - looks for "overdue" mentions in activities
 * @param {string} roomId - Room ID
 * @param {Array} activities - All activities
 * @returns {number} Count of overdue mentions
 */
export function calculateOverdue(roomId, activities) {
  return activities.filter((a) => {
    if (a.room_id !== roomId) return false;
    const summary = a.activity_summary || a.summary || "";
    return /overdue|late|missed deadline/i.test(summary);
  }).length;
}

/**
 * Calculate sentiment for a room based on activity tone
 * @param {string} roomId - Room ID
 * @param {Array} activities - All activities
 * @returns {string} Emoji representing sentiment
 */
export function calculateSentiment(roomId, activities) {
  // Get recent activities for this room
  const recent = activities
    .filter((a) => a.room_id === roomId)
    .slice(0, 20)
    .map((a) => a.activity_summary || a.summary || "")
    .join(" ");

  if (!recent) return "🙂";

  // Simple keyword analysis
  const negativeWords = /critical|urgent|failure|blocked|delayed|error|failed|problem|issue/gi;
  const positiveWords = /completed|resolved|success|launched|fixed|merged|deployed|approved/gi;

  const negCount = (recent.match(negativeWords) || []).length;
  const posCount = (recent.match(positiveWords) || []).length;

  if (negCount > posCount * 2) return "😬"; // Stressed
  if (posCount > negCount) return "😊"; // Happy
  return "🙂"; // Neutral
}

/**
 * Calculate last active time for a room
 * @param {string} roomId - Room ID
 * @param {Array} activities - All activities
 * @returns {string} Formatted relative time (e.g., "5m", "2h", "3d")
 */
export function calculateLastActive(roomId, activities) {
  const roomActivities = activities
    .filter((a) => a.room_id === roomId)
    .sort((a, b) => {
      const timeA = new Date(a.timestamp || a.created_at).getTime();
      const timeB = new Date(b.timestamp || b.created_at).getTime();
      return timeB - timeA;
    });

  if (roomActivities.length === 0) return "Never";

  const lastActivity = roomActivities[0];
  const timestamp = new Date(lastActivity.timestamp || lastActivity.created_at);
  return formatRelativeTime(timestamp);
}

/**
 * Format a timestamp as relative time
 * @param {Date} date - Date to format
 * @returns {string} Formatted time (e.g., "5m", "2h", "3d")
 */
function formatRelativeTime(date) {
  const now = Date.now();
  const diff = now - date.getTime();
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) return `${days}d`;
  if (hours > 0) return `${hours}h`;
  if (minutes > 0) return `${minutes}m`;
  return "Just now";
}

/**
 * Get room summary from activities or use fallback
 * @param {string} roomId - Room ID
 * @param {Array} activities - All activities
 * @param {string|null} aiSummary - AI-generated summary from backend (if available)
 * @returns {string} Room summary
 */
export function getRoomSummary(roomId, activities, aiSummary = null) {
  // Use AI summary if available
  if (aiSummary) return aiSummary;

  // Fallback: Use most recent status-change activity summary
  const latestSummary = activities
    .filter((a) => a.room_id === roomId && a.is_status_change)
    .sort((a, b) => {
      const timeA = new Date(a.timestamp || a.created_at).getTime();
      const timeB = new Date(b.timestamp || b.created_at).getTime();
      return timeB - timeA;
    })[0];

  return latestSummary?.activity_summary || "No recent activity";
}

/**
 * Get key risks for a room from urgent notifications
 * @param {string} roomId - Room ID
 * @param {Array} notifications - All notifications
 * @returns {Array<string>} List of risk descriptions
 */
export function getRoomRisks(roomId, notifications) {
  return notifications
    .filter(
      (n) =>
        (n.room_id === roomId || n.data?.room_id === roomId) &&
        (n.severity === "urgent" || n.data?.severity === "urgent")
    )
    .map((n) => n.title || n.message || "Unknown risk")
    .slice(0, 5); // Top 5 risks
}

/**
 * Get recent activity list for a room
 * @param {string} roomId - Room ID
 * @param {Array} activities - All activities
 * @returns {Array<string>} List of activity summaries
 */
export function getRoomActivity(roomId, activities) {
  return activities
    .filter((a) => a.room_id === roomId && a.is_status_change)
    .sort((a, b) => {
      const timeA = new Date(a.timestamp || a.created_at).getTime();
      const timeB = new Date(b.timestamp || b.created_at).getTime();
      return timeB - timeA;
    })
    .slice(0, 5)
    .map((a) => a.activity_summary || a.summary || "Activity");
}

/**
 * Calculate edges (connections) between rooms
 * Rooms are connected based on:
 * - Shared members
 * - Cross-room notifications
 * - Shared files (from activities)
 * @param {Array} rooms - All rooms
 * @param {Array} activities - All activities
 * @param {Array} notifications - All notifications
 * @returns {Array} Edge data for ReactFlow
 */
export function calculateEdges(rooms, activities, notifications) {
  const edges = [];

  for (let i = 0; i < rooms.length; i++) {
    for (let j = i + 1; j < rooms.length; j++) {
      const roomA = rooms[i];
      const roomB = rooms[j];

      // Calculate shared members
      const membersA = roomA.members || [];
      const membersB = roomB.members || [];
      const sharedMembers = membersA.filter((m) => membersB.includes(m)).length;

      // Calculate cross-room notifications
      const crossNotifs = notifications.filter((n) => {
        const relatedRooms = n.related_rooms || n.data?.related_rooms || [];
        return (
          relatedRooms.includes(roomA.id) && relatedRooms.includes(roomB.id)
        );
      }).length;

      // Calculate shared files from activities
      const filesA = getFilesFromActivities(roomA.id, activities);
      const filesB = getFilesFromActivities(roomB.id, activities);
      const sharedFiles = filesA.filter((f) => filesB.includes(f)).length;

      const overlap = sharedMembers + crossNotifs + sharedFiles;

      if (overlap > 0) {
        edges.push({
          id: `e-${roomA.id}-${roomB.id}`,
          source: roomA.id,
          target: roomB.id,
          strength: Math.min(overlap / 10, 1), // Normalize to 0-1
          overlap,
        });
      }
    }
  }

  return edges;
}

/**
 * Extract file paths from activities for a room
 * @param {string} roomId - Room ID
 * @param {Array} activities - All activities
 * @returns {Array<string>} List of file paths
 */
function getFilesFromActivities(roomId, activities) {
  const files = new Set();

  activities
    .filter((a) => a.room_id === roomId)
    .forEach((a) => {
      // Try to extract file paths from activity data
      const filePath = a.file_path || a.data?.file_path;
      if (filePath) files.add(filePath);

      // Try to extract from summary
      const summary = a.activity_summary || a.summary || "";
      const fileMatches = summary.match(/[\w\/\-\.]+\.\w{2,4}/g) || [];
      fileMatches.forEach((f) => files.add(f));
    });

  return Array.from(files);
}

/**
 * Calculate auto-layout positions for rooms (grid layout)
 * @param {Array} rooms - All rooms
 * @returns {Array} Rooms with position data
 */
export function calculatePositions(rooms) {
  const cols = 3;
  const xSpacing = 300;
  const ySpacing = 200;

  return rooms.map((room, idx) => ({
    ...room,
    position: {
      x: (idx % cols) * xSpacing + 100,
      y: Math.floor(idx / cols) * ySpacing + 100,
    },
  }));
}
