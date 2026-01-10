const isDev = typeof import.meta !== "undefined" && import.meta.env?.DEV;

export const logger = {
  debug: (...args) => {
    if (isDev) console.log("[DEBUG]", ...args);
  },
  info: (...args) => {
    console.log("[INFO]", ...args);
  },
  warn: (...args) => {
    console.warn("[WARN]", ...args);
  },
  error: (...args) => {
    console.error("[ERROR]", ...args);
  },
};
