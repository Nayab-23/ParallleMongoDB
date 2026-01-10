/**
 * ULTRA-FLEXIBLE date parser that handles ANYTHING the backend throws at us
 * Handles: ISO strings, timestamps, human-readable text, unix epochs, RFC strings, null/undefined, broken formats
 */
export function parseDeadline(deadline, deadlineRaw) {
  // Priority 1: explicit raw deadline timestamp/string
  if (deadlineRaw) {
    try {
      const rawDate = new Date(deadlineRaw);
      if (!isNaN(rawDate.getTime())) {
        return rawDate;
      }
    } catch (e) {
      console.warn('[dateUtils] Failed to parse deadline_raw:', deadlineRaw);
    }
  }

  // Handle null/undefined/empty
  if (!deadline || deadline === '' || deadline === 'null' || deadline === 'undefined') {
    return null;
  }

  // If it's already a Date object
  if (deadline instanceof Date) {
    return isNaN(deadline.getTime()) ? null : deadline;
  }

  // If it's a number (timestamp) - handle both milliseconds and seconds
  if (typeof deadline === 'number') {
    try {
      // If it looks like a Unix timestamp in seconds (< year 2100 in ms)
      const timestamp = deadline < 10000000000 ? deadline * 1000 : deadline;
      const date = new Date(timestamp);
      return isNaN(date.getTime()) ? null : date;
    } catch (e) {
      return null;
    }
  }

  // If it's a string, try EVERYTHING
  if (typeof deadline === 'string') {
    const trimmed = deadline.trim();

    // Handle empty strings
    if (!trimmed) {
      return null;
    }

    // Try parsing as a number (string timestamp)
    if (/^\d+$/.test(trimmed)) {
      try {
        const num = parseInt(trimmed);
        const timestamp = num < 10000000000 ? num * 1000 : num;
        const date = new Date(timestamp);
        if (!isNaN(date.getTime())) return date;
      } catch (e) {
        // Continue to other parsers
      }
    }

    // ISO datetime: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS variants
    if (/^\d{4}-\d{2}-\d{2}/.test(trimmed)) {
      try {
        // Normalize various ISO format quirks:
        // - Replace space with T
        // - Handle missing timezone
        // - Handle Z vs +00:00
        let normalized = trimmed
          .replace(/\s+/g, 'T')  // "2026-01-02 06:30:00" -> "2026-01-02T06:30:00"
          .replace(/T{2,}/g, 'T') // Fix double T if already had T
          .replace(/(\d{2}:\d{2}:\d{2})\.(\d+)/, '$1'); // Remove fractional seconds

        // Add timezone if missing
        if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(normalized)) {
          // No timezone, assume local
          normalized += 'Z';
        }

        const date = new Date(normalized);
        if (!isNaN(date.getTime())) return date;
      } catch (e) {
        // Continue to other parsers
      }
    }

    // Human-readable relative time patterns
    const patterns = [
      // "in X units" or "Due in X units"
      {
        regex: /(?:due\s+)?in\s+(\d+\.?\d*)\s*(second|sec|minute|min|hour|hr|h|day|d|week|wk|w|month|mo|year|yr|y)s?/i,
        future: true
      },
      // "X units ago"
      {
        regex: /(\d+\.?\d*)\s*(second|sec|minute|min|hour|hr|h|day|d|week|wk|w|month|mo|year|yr|y)s?\s+ago/i,
        future: false
      },
      // "X units from now"
      {
        regex: /(\d+\.?\d*)\s*(second|sec|minute|min|hour|hr|h|day|d|week|wk|w|month|mo|year|yr|y)s?\s+from\s+now/i,
        future: true
      }
    ];

    for (const pattern of patterns) {
      const match = trimmed.match(pattern.regex);
      if (match) {
        try {
          const amount = parseFloat(match[1]);
          const unit = match[2].toLowerCase();
          const now = new Date();
          const multiplier = pattern.future ? 1 : -1;

          // Map various unit names to standard
          const unitMap = {
            'second': 1000,
            'sec': 1000,
            'minute': 60000,
            'min': 60000,
            'hour': 3600000,
            'hr': 3600000,
            'h': 3600000,
            'day': 86400000,
            'd': 86400000,
            'week': 604800000,
            'wk': 604800000,
            'w': 604800000,
            'month': 2592000000, // ~30 days
            'mo': 2592000000,
            'year': 31536000000, // ~365 days
            'yr': 31536000000,
            'y': 31536000000
          };

          const ms = unitMap[unit];
          if (ms) {
            const resultDate = new Date(now.getTime() + (amount * ms * multiplier));
            if (!isNaN(resultDate.getTime())) return resultDate;
          }
        } catch (e) {
          // Continue to other parsers
        }
      }
    }

    // Special phrases
    const specialPhrases = {
      'now': 0,
      'due now': 0,
      'just now': 0,
      'just passed': 0,
      'today': 0,
      'tonight': () => {
        const d = new Date();
        d.setHours(20, 0, 0, 0);
        return d;
      },
      'tomorrow': () => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        d.setHours(9, 0, 0, 0);
        return d;
      },
      'yesterday': () => {
        const d = new Date();
        d.setDate(d.getDate() - 1);
        d.setHours(9, 0, 0, 0);
        return d;
      },
      'next week': () => {
        const d = new Date();
        d.setDate(d.getDate() + 7);
        return d;
      },
      'last week': () => {
        const d = new Date();
        d.setDate(d.getDate() - 7);
        return d;
      }
    };

    const lowerTrimmed = trimmed.toLowerCase();
    for (const [phrase, value] of Object.entries(specialPhrases)) {
      if (lowerTrimmed.includes(phrase)) {
        try {
          if (typeof value === 'function') {
            return value();
          } else {
            return new Date(Date.now() + value);
          }
        } catch (e) {
          // Continue
        }
      }
    }

    // Try RFC 2822 / RFC 1123 (e.g., "Mon, 02 Jan 2026 06:30:00 GMT")
    try {
      const date = new Date(trimmed);
      if (!isNaN(date.getTime())) {
        // Verify it's a reasonable date (not year 0001 or 9999)
        const year = date.getFullYear();
        if (year > 1970 && year < 2100) {
          return date;
        }
      }
    } catch (e) {
      // Continue
    }

    // Try parsing MM/DD/YYYY or DD/MM/YYYY
    const slashMatch = trimmed.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
    if (slashMatch) {
      try {
        const [, p1, p2, year, hour = 0, minute = 0, second = 0] = slashMatch;
        const fullYear = year.length === 2 ? 2000 + parseInt(year) : parseInt(year);

        // Try MM/DD/YYYY (US format)
        let date = new Date(fullYear, parseInt(p1) - 1, parseInt(p2), parseInt(hour), parseInt(minute), parseInt(second));
        if (!isNaN(date.getTime())) return date;

        // Try DD/MM/YYYY (EU format)
        date = new Date(fullYear, parseInt(p2) - 1, parseInt(p1), parseInt(hour), parseInt(minute), parseInt(second));
        if (!isNaN(date.getTime())) return date;
      } catch (e) {
        // Continue
      }
    }

    // Last resort: try Date.parse with various manipulations
    const variations = [
      trimmed,
      trimmed.replace(/[^\d\s:/-]/g, ''), // Remove special chars
      trimmed.replace(/\s+/g, ' '), // Normalize whitespace
      trimmed.replace(/[_]/g, ' '), // Underscores to spaces
    ];

    for (const variation of variations) {
      try {
        const timestamp = Date.parse(variation);
        if (!isNaN(timestamp)) {
          const date = new Date(timestamp);
          const year = date.getFullYear();
          if (year > 1970 && year < 2100) {
            return date;
          }
        }
      } catch (e) {
        // Continue
      }
    }
  }

  // If it's an object with date properties, try to extract
  if (typeof deadline === 'object' && deadline !== null) {
    try {
      // Try common object date formats
      if (deadline.date) return parseDeadline(deadline.date);
      if (deadline.datetime) return parseDeadline(deadline.datetime);
      if (deadline.timestamp) return parseDeadline(deadline.timestamp);
      if (deadline.$date) return parseDeadline(deadline.$date); // MongoDB format

      // Try ISO object format {year, month, day, hour, minute, second}
      if (deadline.year && deadline.month && deadline.day) {
        const date = new Date(
          deadline.year,
          deadline.month - 1, // JS months are 0-indexed
          deadline.day,
          deadline.hour || 0,
          deadline.minute || 0,
          deadline.second || 0
        );
        if (!isNaN(date.getTime())) return date;
      }
    } catch (e) {
      // Continue
    }
  }

  // Couldn't parse - log warning and return null
  console.warn('[dateUtils] Could not parse deadline:', deadline, typeof deadline);
  return null;
}

/**
 * Format a deadline for display
 * Returns a user-friendly string like "tomorrow at 6:30 AM"
 * NEVER throws - always returns null or a valid string
 */
export function formatDeadlineDisplay(deadline, deadlineRaw) {
  try {
    const date = parseDeadline(deadline, deadlineRaw);

    if (!date || isNaN(date.getTime())) {
      return null; // Invalid date
    }

    const now = new Date();
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);

    // Compare calendar dates (ignoring time)
    const deadlineDate = date.toDateString();
    const todayDate = now.toDateString();
    const tomorrowDate = tomorrow.toDateString();

    // Format time - with fallback
    let timeStr;
    try {
      timeStr = date.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
      });
    } catch (e) {
      // Fallback to simple format
      const hours = date.getHours();
      const minutes = date.getMinutes();
      const ampm = hours >= 12 ? 'PM' : 'AM';
      const displayHours = hours % 12 || 12;
      timeStr = `${displayHours}:${minutes.toString().padStart(2, '0')} ${ampm}`;
    }

    // Determine day label
    let dayLabel;
    if (deadlineDate === todayDate) {
      dayLabel = "today";
    } else if (deadlineDate === tomorrowDate) {
      dayLabel = "tomorrow";
    } else {
      try {
        const options = { weekday: 'long', month: 'short', day: 'numeric' };
        dayLabel = date.toLocaleDateString('en-US', options);
      } catch (e) {
        // Fallback to simple date string
        dayLabel = date.toDateString();
      }
    }

    return `${dayLabel} at ${timeStr}`;
  } catch (e) {
    console.warn('[dateUtils] Error formatting deadline:', deadline, e);
    return null;
  }
}

/**
 * Calculate time until deadline
 * Returns string like "in 8 hours" or "in 2 days"
 * NEVER throws - always returns null or a valid string
 */
export function getTimeUntil(deadline, deadlineRaw) {
  try {
    const date = parseDeadline(deadline, deadlineRaw);

    if (!date || isNaN(date.getTime())) {
      return null;
    }

    const now = new Date();
    const diffMs = date - now;
    const diffMinutes = diffMs / (1000 * 60);
    const diffHours = diffMs / (1000 * 60 * 60);
    const diffDays = diffMs / (1000 * 60 * 60 * 24);

    // Handle edge cases
    if (!isFinite(diffHours)) {
      return null;
    }

    if (diffHours < -24) {
      const daysOverdue = Math.abs(Math.round(diffDays));
      return `${daysOverdue} day${daysOverdue !== 1 ? 's' : ''} overdue`;
    } else if (diffHours < -1) {
      return 'overdue';
    } else if (diffMinutes < 1) {
      return 'due now';
    } else if (diffHours < 1) {
      return `in ${Math.round(diffMinutes)} min`;
    } else if (diffHours < 24) {
      return `in ${Math.round(diffHours)} hr${Math.round(diffHours) !== 1 ? 's' : ''}`;
    } else {
      return `in ${Math.round(diffDays)} day${Math.round(diffDays) !== 1 ? 's' : ''}`;
    }
  } catch (e) {
    console.warn('[dateUtils] Error calculating time until:', deadline, e);
    return null;
  }
}

/**
 * Check if a date string is valid
 */
export function isValidDate(dateStr) {
  const date = parseDeadline(dateStr);
  return date !== null && !isNaN(date.getTime());
}
