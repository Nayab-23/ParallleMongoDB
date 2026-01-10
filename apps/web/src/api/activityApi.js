import { API_BASE_URL } from "../config";

export async function getActivityHistory(userId = null, days = 7, limit = 50) {
  const params = new URLSearchParams();
  if (userId) params.append("user_id", userId);
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

export async function getTeamActivity() {
  const response = await fetch(`${API_BASE_URL}/api/team/activity`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch team activity: ${response.status}`);
  }

  return response.json();
}
