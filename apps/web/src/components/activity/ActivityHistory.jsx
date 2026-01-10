import { useEffect, useState } from "react";
import { getActivityHistory } from "../../api/activityApi";
import "./ActivityHistory.css";

export default function ActivityHistory({ userId = null, days = 7, isAdmin = false }) {
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [timeRange, setTimeRange] = useState(days);
  const [retryCount, setRetryCount] = useState(0);

  const loadActivities = async (isRetry = false) => {
    try {
      setLoading(true);
      if (!isRetry) {
        setError(null);
      }

      const data = await getActivityHistory(userId, timeRange, 50);

      // ============ DEBUG LOGGING ============
      console.log('📊 [Activity Count] Total activities received:', data.activities?.length || 0);

      if (data.activities && data.activities.length > 0) {
        const firstActivity = data.activities[0];

        console.group('🔍 [Activity Debug] Complete Analysis');

        // 1. Raw data inspection
        console.log('📦 Raw Activity Object:', firstActivity);
        console.log('📝 Raw Summary:', firstActivity.summary);
        console.log('📊 Summary Type:', typeof firstActivity.summary);
        console.log('📏 Summary Length:', firstActivity.summary?.length);

        if (firstActivity.summary) {
          // 2. Character code analysis
          const first30Chars = firstActivity.summary.substring(0, 30);
          const charAnalysis = first30Chars.split('').map((char, idx) => ({
            index: idx,
            char: char,
            code: char.charCodeAt(0),
            hex: '0x' + char.charCodeAt(0).toString(16),
            isControl: char.charCodeAt(0) < 32,
            isNewline: char === '\n' || char === '\r',
            isSpace: char === ' ',
            category: (() => {
              const c = char.charCodeAt(0);
              if (c < 32) return 'CONTROL';
              if (c === 32) return 'SPACE';
              if (c === 9) return 'TAB';
              if (c === 10) return 'LF';
              if (c === 13) return 'CR';
              if (c >= 32 && c <= 126) return 'ASCII';
              if (c === 0x2028) return 'LINE_SEP';
              if (c === 0x2029) return 'PARA_SEP';
              if (c >= 160) return 'UNICODE';
              return 'OTHER';
            })()
          }));

          console.table(charAnalysis);

          // 3. Pattern detection
          const patterns = {
            hasNewlines: /[\n\r]/.test(firstActivity.summary),
            hasControlChars: /[\x00-\x1F]/.test(firstActivity.summary),
            hasLineSeparator: /\u2028/.test(firstActivity.summary),
            hasParaSeparator: /\u2029/.test(firstActivity.summary),
            hasNonBreakingSpace: /\u00A0/.test(firstActivity.summary),
            hasMultipleSpaces: /\s{2,}/.test(firstActivity.summary),
            containsOnly: firstActivity.summary.split('').every(c => {
              const code = c.charCodeAt(0);
              return (code >= 32 && code <= 126) || code >= 160;
            })
          };

          console.log('🔎 Pattern Detection:', patterns);

          // 4. Test normalization
          const beforeNorm = firstActivity.summary;
          const afterNorm = normalizeSummary(beforeNorm);

          console.log('🧪 Normalization Test:');
          console.log('  Before length:', beforeNorm.length);
          console.log('  After length:', afterNorm.length);
          console.log('  Before (first 100):', beforeNorm.substring(0, 100));
          console.log('  After (first 100):', afterNorm.substring(0, 100));
          console.log('  Changed:', beforeNorm !== afterNorm);

          // 5. Check if it's an array somehow
          if (Array.isArray(firstActivity.summary)) {
            console.error('❌ SUMMARY IS AN ARRAY! This is the bug!');
            console.log('Array contents:', firstActivity.summary);
          }

          // 6. Check if it's an object
          if (typeof firstActivity.summary === 'object' && firstActivity.summary !== null) {
            console.error('❌ SUMMARY IS AN OBJECT! This is the bug!');
            console.log('Object contents:', firstActivity.summary);
          }
        }

        console.groupEnd();
      }
      // ============ END DEBUG ============

      setActivities(data.activities || []);
      setError(null);
      setRetryCount(0); // Reset retry count on success

    } catch (err) {
      console.error("[Activity History] Failed to load:", err);
      setError("Failed to load activity history");

      // Auto-retry up to 2 times
      if (retryCount < 2 && !isRetry) {
        setTimeout(() => {
          setRetryCount(prev => prev + 1);
          loadActivities(true);
        }, 2000); // Retry after 2 seconds
      }

    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadActivities();

    // Refresh every minute
    const interval = setInterval(() => loadActivities(), 60000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, timeRange]);

  // Manual retry handler
  const handleRetry = () => {
    setRetryCount(0);
    loadActivities();
  };

  const formatTimestamp = (isoString) => {
    if (!isoString) return "";
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  };

  const getActorName = (activity) => {
    const actor =
      activity.user_name ||
      activity.actor_name ||
      activity.name ||
      activity.user;
    return typeof actor === "string" ? actor.trim() : "";
  };

  const normalizeSummary = (value) => {
    if (!value) return "";

    // Convert to string if not already
    let text = typeof value === "string" ? value : String(value);

    // NUCLEAR OPTION 1: Strip ALL control characters byte-by-byte
    let cleaned = '';
    for (let i = 0; i < text.length; i++) {
      const code = text.charCodeAt(i);

      // Only keep safe printable characters
      if (code >= 32 && code <= 126) {
        // Standard ASCII printable (space through tilde)
        cleaned += text[i];
      } else if (code >= 160 && code <= 55295) {
        // Extended Unicode (excluding surrogates and special chars)
        cleaned += text[i];
      } else if (code >= 57344 && code <= 65533) {
        // Private use and higher Unicode (excluding special)
        cleaned += text[i];
      } else if (code === 9 || code === 32) {
        // Tab or space - convert to single space
        cleaned += ' ';
      } else if (code === 10 || code === 13) {
        // Line feed or carriage return - convert to space
        cleaned += ' ';
      }
      // Everything else (including \u2028, \u2029, control chars) is DROPPED
    }

    // NUCLEAR OPTION 2: Collapse ALL whitespace
    cleaned = cleaned
      .replace(/\s+/g, ' ')           // Multiple spaces → one space
      .replace(/\u00A0+/g, ' ')       // Non-breaking spaces → regular space
      .replace(/[\u2000-\u200B]/g, ' ') // All Unicode spaces → regular space
      .trim();                         // Remove leading/trailing

    // NUCLEAR OPTION 3: Limit length to prevent issues
    if (cleaned.length > 500) {
      cleaned = cleaned.substring(0, 497) + '...';
    }

    return cleaned;
  };

  const getSummaryText = (activity) => {
    // Get raw text from any available field
    const rawText = activity.summary ||
                    activity.message ||
                    activity.description ||
                    "";

    // ALWAYS normalize, even if it looks clean
    const cleaned = normalizeSummary(rawText);

    // Fallback if normalization results in empty string
    if (!cleaned || cleaned.trim().length === 0) {
      const actor = getActorName(activity);
      if (actor) return `${actor}: [No recent activity]`;
      return "[No recent activity]";
    }

    return cleaned;
  };

  if (loading && activities.length === 0) {
    return <div className="activity-history-loading">Loading activity...</div>;
  }

  if (error && activities.length === 0) {
    return (
      <div className="activity-history-error">
        <p>{error}</p>
        {retryCount < 2 && <p className="retry-info">Retrying... ({retryCount + 1}/2)</p>}
        <button onClick={handleRetry} className="retry-btn">
          🔄 Retry
        </button>
      </div>
    );
  }

  return (
    <div className="activity-history">
      <div className="activity-history-header">
        <h3>Activity History</h3>
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(Number(e.target.value))}
          className="time-range-select"
        >
          <option value={1}>Today</option>
          <option value={7}>This Week</option>
          <option value={30}>This Month</option>
        </select>
      </div>

      <div className="activity-timeline">
        {activities.length === 0 ? (
          <div className="no-activities">No activity yet</div>
        ) : (
          activities.map((activity, index) => {
            const summaryText = getSummaryText(activity);

            // DEBUG: Log render data for first 3 items
            if (index < 3) {
              console.log(`🎨 [Render ${index}]`, {
                summaryText,
                length: summaryText.length,
                type: typeof summaryText,
                isArray: Array.isArray(summaryText),
                isObject: typeof summaryText === 'object',
                first20Chars: summaryText.substring(0, 20)
              });
            }

            return (
              <div
                key={activity.id}
                className={`activity-item ${
                  activity.is_status_change ? "status-change" : ""
                }`}
              >
                <div className="activity-time">
                  {formatTimestamp(activity.timestamp)}
                </div>
                <div className="activity-content">
                  {isAdmin &&
                    activity.similarity_to_status != null && (
                      <div className="activity-debug">
                        Similarity to status:{" "}
                        {(activity.similarity_to_status * 100).toFixed(0)}%
                        {activity.similarity_to_previous != null && (
                          <>
                            , to previous:{" "}
                            {(activity.similarity_to_previous * 100).toFixed(0)}%
                          </>
                        )}
                      </div>
                    )}
                  <div className="activity-summary">{String(summaryText)}</div>
                  {activity.is_status_change && (
                    <span className="status-badge">Status Change</span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
