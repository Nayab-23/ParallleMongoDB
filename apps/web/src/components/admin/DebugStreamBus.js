// Lightweight event bus for admin diagnostics stream
const listeners = new Set();

export function subscribeDebugStream(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function emitDebugStream(event) {
  listeners.forEach((fn) => {
    try {
      fn(event);
    } catch (err) {
      // swallow listener errors
      console.error("[AdminDebugStream] listener error", err);
    }
  });
}
