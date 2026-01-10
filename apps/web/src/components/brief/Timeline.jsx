import { useEffect, useMemo } from "react";
import "./Timeline.css";
import { formatDeadlineDisplay, getTimeUntil } from "../../utils/dateUtils";

export default function Timeline({
  data = {},
  items,
  onComplete = () => {},
  onDelete = () => {},
  onRefresh = null,
}) {
  // Support both shapes: {1d,7d,28d} and {today,this_week,this_month}
  const timelineData = items || data || {};
  const timeframes = useMemo(
    () => [
      {
        key: "today",
        fallbacks: ["1d"],
        title: "Daily Goals",
        icon: "",
        empty: "No urgent tasks today 🎉",
      },
      {
        key: "this_week",
        fallbacks: ["7d"],
        title: "Weekly Focus",
        icon: "",
        empty: "Week is clear - great planning!",
      },
      {
        key: "this_month",
        fallbacks: ["28d"],
        title: "Monthly Objectives",
        icon: "",
        empty: "No monthly milestones set yet",
      },
    ],
    []
  );

  // // Diagnostic logging for Daily (1d) pipeline
  // useEffect(() => {
  //   const timeline = timelineData || {};
  //   const dailySection =
  //     timeline["1d"] ||
  //     timeline.today ||
  //     (Array.isArray(timeline) ? timeline[0] : {});

  //   const dailyUrgent = Array.isArray(dailySection?.urgent)
  //     ? dailySection.urgent
  //     : [];
  //   const dailyNormal = Array.isArray(dailySection?.normal)
  //     ? dailySection.normal
  //     : [];

  //   const allDaily = [...dailyUrgent, ...dailyNormal];
  //   const uniqueDaily = Array.from(
  //     new Map(
  //       allDaily.map((task, idx) => [
  //         task?.source_id || task?.signature || task?.id || `idx-${idx}`,
  //         task,
  //       ])
  //     ).values()
  //   );

  //   console.log("📊 [TIMELINE DEBUG] timelineData:", timelineData);
  //   console.log("📊 [DAILY] 1d object:", dailySection);
  //   console.log("📊 [DAILY] 1d.urgent:", dailyUrgent);
  //   console.log("📊 [DAILY] 1d.normal:", dailyNormal);
  //   console.log("📊 [DAILY] dailyUrgent length:", dailyUrgent.length);
  //   console.log("📊 [DAILY] dailyNormal length:", dailyNormal.length);
  //   console.log("📊 [DAILY] combined allDaily:", allDaily);
  //   console.log("📊 [DAILY] allDaily length:", allDaily.length);
  //   console.log("📊 [DAILY] uniqueDaily after dedup:", uniqueDaily);
  //   console.log("📊 [DAILY] uniqueDaily length:", uniqueDaily.length);
  //   console.log(
  //     "📊 [DAILY] dismissedItems: (not available in Timeline component)"
  //   );
  // }, [timelineData]);

  return (
    <div className="timeline-container">
      {timeframes.map((tf) => {
        const section =
          timelineData?.[tf.key] ||
          (tf.fallbacks || []).reduce(
            (acc, alt) => acc || timelineData?.[alt],
            null
          ) ||
          {};
        const count = getTotalTaskCount(section);
        return (
          <TimelineSection
            key={tf.key}
            title={tf.title}
            icon={tf.icon}
            count={count}
            items={section}
            emptyMessage={tf.empty}
            onComplete={onComplete}
            onDelete={onDelete}
            onRefresh={tf.key === "today" ? onRefresh : null}
          />
        );
      })}
    </div>
  );
}

function TimelineSection({
  title,
  icon,
  count,
  items,
  emptyMessage,
  onComplete,
  onDelete,
  onRefresh,
}) {
  const dedupedTasks = useMemo(() => dedupeTasks(items), [items]);

  return (
    <div className="timeline-section">
      <div className="section-header">
        <div className="section-title-wrap">
          <span className="section-icon">{icon}</span>
          <h2>{title}</h2>
          <span className="task-count-badge">
            {count} {count === 1 ? "task" : "tasks"}
          </span>
        </div>
      </div>

      <div className="section-content">
        {count === 0 ? (
          <div className="empty-timeline-section">
            <p className="empty-message">{emptyMessage}</p>
            {onRefresh && (
              <button className="refresh-timeline-btn" onClick={onRefresh}>
                🔄 Refresh Timeline
              </button>
            )}
          </div>
        ) : (
          dedupedTasks.map(({ task, priority }) => (
            <TaskCard
              key={
                task.source_id ||
                task.signature ||
                task.id ||
                task.title
              }
              task={task}
              priority={priority}
              onComplete={onComplete}
              onDelete={onDelete}
            />
          ))
        )}
      </div>
    </div>
  );
}

function TaskCard({ task = {}, priority = "normal", onComplete, onDelete }) {
  const signature = task.signature || task.id || task.title;
  const priorityBorder = {
    urgent: "border-urgent",
    normal: "border-normal",
  }[priority];

  // Extract deadline from multiple sources, including from detail field if missing
  let deadline = task.deadline || task.date;
  const deadlineRaw = task.deadline_raw || task.deadlineRaw;
  const description = task.detail || task.description;

  // If no deadline but description contains ISO timestamp, extract it
  if (!deadline && description) {
    const isoMatch = description.match(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}/i);
    if (isoMatch) {
      deadline = isoMatch[0].replace(' ', 'T'); // Normalize space to T
    }
  }

  const deadlineText = formatDeadlineDisplay(deadline, deadlineRaw);
  const relativeTime = getTimeUntil(deadline, deadlineRaw);
  const isRecurring = task.is_recurring === true;

  // Filter out raw ISO timestamp patterns from description (both T and space separators, case insensitive)
  const cleanDescription = description
    ? description.replace(/Scheduled for \d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}\.?/gi, '')
                 .replace(/Tasks at \d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}\.?/gi, '')
                 .trim()
    : '';

  return (
    <div className={`task-card ${priorityBorder} ${isRecurring ? 'recurring' : ''}`}>
      <div className="task-top">
        <div className="task-titles">
          <div className="task-title-row">
            <h3>{task.title || "Task"}</h3>
            {isRecurring && (
              <span className="recurrence-badge" title={task.recurrence_description || "Recurring event"}>
                🔁 {task.recurrence_description || "Recurring"}
              </span>
            )}
          </div>
          {cleanDescription ? <p>{cleanDescription}</p> : null}
          {isRecurring && task.instance_count > 1 && (
            <div className="recurrence-info">
              <span className="instance-count">
                {task.instance_count} upcoming occurrence{task.instance_count !== 1 ? 's' : ''}
              </span>
              {task.next_occurrence && formatDeadlineDisplay(task.next_occurrence) && (
                <span className="next-occurrence">
                  Next: {formatDeadlineDisplay(task.next_occurrence)}
                </span>
              )}
            </div>
          )}
          {!isRecurring && deadline && (
            deadlineText ? (
              <div className="task-deadline-container">
                <span className="task-deadline-date">
                  <span role="img" aria-label="deadline">⏰</span> {deadlineText}
                </span>
                {relativeTime && (
                  <span className="task-deadline-relative">({relativeTime})</span>
                )}
              </div>
            ) : (
              <div className="task-deadline-container">
                <span className="task-deadline-date">
                  <span role="img" aria-label="deadline">⏰</span> Scheduled (time pending)
                </span>
              </div>
            )
          )}
        </div>
        <div className="task-actions">
          <button onClick={() => onComplete({ ...task, signature })} title="Complete">
            ✓
          </button>
          <button
            onClick={() => onDelete({ ...task, signature })}
            title={isRecurring && task.instance_count > 1
              ? `Delete all ${task.instance_count} occurrences`
              : "Delete"}
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  );
}

// Helpers
function getTotalTaskCount(data) {
  if (!data) return 0;
  return dedupeTasks(data).length;
}

function dedupeTasks(section) {
  const urgent = Array.isArray(section?.urgent) ? section.urgent : [];
  const normal = Array.isArray(section?.normal) ? section.normal : [];
  const combined = [
    ...urgent.map((task) => ({ task, priority: "urgent" })),
    ...normal.map((task) => ({ task, priority: "normal" })),
  ];

  const map = new Map();
  let fallbackId = 0;

  combined.forEach(({ task, priority }) => {
    const key =
      task?.source_id ||
      task?.signature ||
      task?.id ||
      task?.title ||
      `task-${fallbackId++}`;
    if (!map.has(key)) {
      map.set(key, { task, priority });
    }
  });

  return Array.from(map.values());
}
