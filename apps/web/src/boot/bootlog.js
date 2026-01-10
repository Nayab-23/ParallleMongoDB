const BOOTLOG_MAX_EVENTS = 50;

let debugFlag = false;
try {
  debugFlag =
    (typeof import.meta !== "undefined" && import.meta.env?.DEV) ||
    (typeof localStorage !== "undefined" && localStorage.getItem("DEBUG_BOOTLOG") === "1");
} catch {
  debugFlag = false;
}

const existing = typeof window !== "undefined" ? window.__bootlog : undefined;
const events = Array.isArray(existing?.events) ? existing.events : [];

export const pushBootlog = (entry) => {
  try {
    const normalized = {
      ts: new Date().toISOString(),
      ...entry,
    };
    events.push(normalized);
    if (events.length > BOOTLOG_MAX_EVENTS) {
      events.shift();
    }
    return normalized;
  } catch {
    return null;
  }
};

export const dumpBootlog = (label = "dump", force = false) => {
  try {
    if (!debugFlag && !force) return;
    if (typeof console?.group === "function") console.group(`[BOOTLOG] ${label}`);
    events.forEach((evt, idx) => {
      try {
        console.log(idx, evt);
      } catch {
        /* ignore log errors */
      }
    });
    if (typeof console?.groupEnd === "function") console.groupEnd();
  } catch {
    /* never throw from dump */
  }
};

const bootlog = existing || { events };
bootlog.max = BOOTLOG_MAX_EVENTS;
bootlog.push = pushBootlog;
bootlog.dump = dumpBootlog;
bootlog.debug = debugFlag;

if (typeof window !== "undefined") {
  window.__bootlog = bootlog;
  window.__pushBootlog = pushBootlog;
  window.__dumpBootlog = dumpBootlog;
}

if (typeof window !== "undefined" && !window.__bootlogListenersAttached) {
  window.__bootlogListenersAttached = true;
  pushBootlog({ tag: "listeners_attached" });

  const logErrorEvent = (label, detail) => {
    try {
      const payload = {
        ...detail,
        href: window.location?.href,
        lastEvents: bootlog.events.slice(-BOOTLOG_MAX_EVENTS),
      };
      console.error(label, payload);
      dumpBootlog(label.replace(/[[\]]/g, ""), true);
    } catch {
      /* swallow logging errors only */
    }
  };

  window.addEventListener("error", (event) => {
    try {
      const detail = {
        tag: "window.error",
        message: event?.message,
        filename: event?.filename,
        lineno: event?.lineno,
        colno: event?.colno,
        name: event?.error?.name,
        errorMessage: event?.error?.message,
        stack: event?.error?.stack,
      };
      pushBootlog(detail);
      logErrorEvent("[BOOT ERROR]", detail);
    } catch {
      /* never throw from handler */
    }
  });

  window.addEventListener("unhandledrejection", (event) => {
    try {
      const reason = event?.reason || {};
      const detail = {
        tag: "unhandledrejection",
        message: reason?.message || String(reason),
        name: reason?.name,
        stack: reason?.stack,
      };
      pushBootlog(detail);
      logErrorEvent("[BOOT REJECTION]", detail);
    } catch {
      /* never throw from handler */
    }
  });
}

export const bootlogDebugEnabled = debugFlag;

export default bootlog;
