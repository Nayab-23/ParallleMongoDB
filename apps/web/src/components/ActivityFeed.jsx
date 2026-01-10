import { useEffect, useState } from "react";

export default function ActivityFeed() {
  const [activities, setActivities] = useState([]);
  const [relevantOnly, setRelevantOnly] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchActivities();
    const interval = setInterval(fetchActivities, 30000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [relevantOnly]);

  const fetchActivities = async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `/api/activity/feed?relevant_only=${relevantOnly}&limit=30`,
        {
          credentials: "include",
          headers: { Authorization: `Bearer ${localStorage.getItem("token") || ""}` },
        }
      );
      const data = await res.json();
      const list = Array.isArray(data?.activities) ? data.activities : [];
      setActivities(list);
    } catch (err) {
      console.error("Error fetching activity:", err);
    } finally {
      setLoading(false);
    }
  };

  const getIcon = (type) => {
    if (type === "task_completed") return "✅";
    if (type === "task_deleted") return "🗑️";
    if (type === "task_created") return "🆕";
    return "📌";
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return "";
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return "just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="notifications-panel flex flex-col h-full">
      <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Team Activity</h2>
          <p className="text-sm text-gray-500">What teammates are working on</p>
        </div>
        <button
          onClick={() => setRelevantOnly((r) => !r)}
          className="text-sm px-3 py-2 rounded-md border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800"
        >
          {relevantOnly ? "Showing relevant" : "All activity"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && activities.length === 0 ? (
          <div className="p-6 text-center text-gray-500">Loading activity…</div>
        ) : activities.length === 0 ? (
          <div className="p-6 text-center text-gray-500">No recent activity yet.</div>
        ) : (
          <div className="divide-y divide-gray-200 dark:divide-gray-700">
            {activities.map((act) => (
              <div key={act.id || act.timestamp} className="p-4 flex gap-3">
                <span className="text-2xl flex-shrink-0">{getIcon(act.type)}</span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm text-gray-900 dark:text-gray-100">
                    {act.actor_name || "Someone"} {act.verb || "updated"} {act.subject || "a task"}
                  </div>
                  {act.description && (
                    <div className="text-sm text-gray-600 dark:text-gray-400">{act.description}</div>
                  )}
                  <div className="text-xs text-gray-500 mt-1">
                    {formatTimestamp(act.created_at || act.timestamp)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
