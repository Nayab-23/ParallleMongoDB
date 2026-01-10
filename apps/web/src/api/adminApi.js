/**
 * Admin API Wrapper
 *
 * Centralized API client for all admin dashboard endpoints.
 *
 * Features:
 * - Automatic credentials: "include" for cookie-based auth
 * - Normalized error handling with { status, message, body }
 * - Consistent response parsing
 * - Better debugging visibility
 *
 * All functions throw errors with structured data for UI display.
 */

import { API_BASE_URL } from "../config";
import { emitDebugStream } from "../components/admin/DebugStreamBus";

/**
 * Generate unique request ID for tracking
 */
function generateRequestId() {
  return `req_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

/**
 * Centralized admin fetch wrapper with comprehensive debugging
 *
 * NEVER THROWS - Always returns normalized response object
 *
 * @param {string} url - Full URL to fetch
 * @param {object} options - Fetch options
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object, request_id: string, duration_ms: number, status: number}>}
 */
const responseCache = new Map();

async function adminFetch(url, options = {}) {
  const request_id = generateRequestId();
  const startTime = Date.now();

  const method = options.method || "GET";
  const adminDebugEnabled =
    typeof localStorage !== "undefined" && localStorage.getItem("ADMIN_DEBUG") === "1";
  const cacheKey = options.cacheKey || url;
  const ttlMs = options.ttlMs || 0;
  const forceRefresh = options.forceRefresh === true;
  const now = Date.now();

  if (!forceRefresh && ttlMs > 0 && responseCache.has(cacheKey)) {
    const cached = responseCache.get(cacheKey);
    if (now - cached.ts < ttlMs) {
      return cached.value;
    }
  }

  console.log(`[AdminAPI] 🚀 ${request_id} Starting ${method} ${url}`);

  const config = {
    credentials: "include", // Always send cookies
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  };

  let response;
  let body;
  let status = 0;
  let success = false;
  let error = null;
  let requestIdHeader = null;
  let durationHeader = null;
  let adminHeaders = {};

  try {
    response = await fetch(url, { ...config, signal: options.signal });
    status = response.status;
    requestIdHeader = response.headers.get("x-request-id");
    durationHeader = Number(response.headers.get("x-duration-ms")) || null;
    adminHeaders = {
      adminRequestId: response.headers.get("x-admin-request-id"),
      adminDurationMs: Number(response.headers.get("x-admin-duration-ms")) || null,
      adminRoute: response.headers.get("x-admin-route"),
      adminHandler: response.headers.get("x-admin-handler"),
      snapshotKey: response.headers.get("x-admin-snapshot-key"),
      snapshotAge: response.headers.get("x-admin-snapshot-age"),
      backendRevision: response.headers.get("x-admin-backend-revision"),
    };

    const elapsed = Date.now() - startTime;
    console.log(`[AdminAPI] ⏱️  ${request_id} Response ${status} in ${elapsed}ms`);

    // Parse response body safely
    const contentType = response.headers.get("content-type");
    try {
      if (contentType && contentType.includes("application/json")) {
        body = await response.json();
      } else {
        const text = await response.text();
        body = { rawResponse: text };
      }
    } catch (parseError) {
      console.error(`[AdminAPI] ❌ ${request_id} JSON parse failed:`, parseError);
      body = {
        parseError: "Failed to parse response body",
        parseErrorMessage: parseError.message
      };
    }

  } catch (networkError) {
    // Network failure (no response from server)
    const elapsed = Date.now() - startTime;
    const aborted = networkError?.name === "AbortError";
    console.error(`[AdminAPI] 💥 ${request_id} Network error after ${elapsed}ms:`, networkError);

    status = 0;
    success = false;
    error = aborted ? "Request aborted" : "Network error - cannot reach backend";
    body = {
      networkError: networkError.message,
      networkErrorType: networkError.name
    };
  }

  const duration_ms = Date.now() - startTime;
  const resolvedRequestId = requestIdHeader || body?.request_id || request_id;
  const resolvedDuration = durationHeader || body?.duration_ms || duration_ms;

  // Envelope vs legacy detection
  const isEnvelope = typeof body?.success === "boolean";

  if (isEnvelope) {
    success = !!body.success;
    const envelopeError = body?.error;
    if (!success) {
      error =
        typeof envelopeError === "object"
          ? envelopeError
          : { message: envelopeError || body?.message || body?.detail || "Request failed", status };
    } else {
      error = null;
    }
  } else {
    // Legacy shape
    if (status >= 400) {
      success = false;
      error = {
        code: "HTTP_ERROR",
        message: body?.detail || body?.error || body?.message || "Request failed",
        details: body,
        status,
      };
    } else {
      success = true;
      error = null;
    }
  }

  const normalizedError = success
    ? null
    : typeof error === "object"
    ? error
    : {
        message: typeof error === "string" ? error : error?.message || "Unknown error",
        status,
        request_id: resolvedRequestId,
        body,
      };

  // Normalize data for envelope/legacy
  const normalizedData = isEnvelope
    ? success
      ? body?.data ?? body
      : null
    : success
    ? body
    : null;

  // Console mirroring
  if (!success || status >= 400) {
    console.groupCollapsed(`[ADMIN_API_ERROR] ${method} ${url}`);
    console.log("request_id:", resolvedRequestId);
    console.log("status:", status);
    console.log("duration_ms:", resolvedDuration);
    console.log("error:", normalizedError);
    console.log("debug:", { headers: { requestIdHeader, durationHeader }, measured: duration_ms });
    console.log("raw_body:", body);
    console.groupEnd();
  } else if (adminDebugEnabled && body?.debug) {
    console.groupCollapsed(`[ADMIN_API_DEBUG] ${method} ${url}`);
    console.log("request_id:", resolvedRequestId);
    console.log("duration_ms:", resolvedDuration);
    console.log("debug:", body.debug);
    console.groupEnd();
  }

  // Construct normalized response
  const result = {
    success,
    data: normalizedData,
    error: normalizedError,
    debug: {
      url,
      method,
      request_id: resolvedRequestId,
      duration_ms: resolvedDuration,
      status,
      timestamp: new Date().toISOString(),
      responseBody: body,
      legacy: !isEnvelope,
      headers: adminHeaders,
    },
    request_id: resolvedRequestId,
    duration_ms: resolvedDuration,
    status,
    headers: adminHeaders,
  };

  const diagEvent = {
    client_request_id: request_id,
    endpoint: url,
    status,
    envelope_request_id: body?.request_id || null,
    header_request_id: adminHeaders.adminRequestId || requestIdHeader,
    backend_revision: adminHeaders.backendRevision,
    handler: adminHeaders.adminHandler,
    route: adminHeaders.adminRoute,
    duration_ms: adminHeaders.adminDurationMs || resolvedDuration,
    snapshot_key: adminHeaders.snapshotKey,
    snapshot_age: adminHeaders.snapshotAge,
    contract_ok: isEnvelope,
    error_code: body?.error?.code ?? null,
  };

  console.info("[ADMIN_DIAG]", diagEvent);
  emitDebugStream(diagEvent);

  console.log(`[AdminAPI] 📦 ${request_id} Returning normalized response:`, {
    success,
    hasData: !!result.data,
    error: normalizedError,
    duration_ms: resolvedDuration,
    status
  });

  if (ttlMs > 0 && success) {
    responseCache.set(cacheKey, { ts: now, value: result });
  }

  return result;
}

/**
 * Test admin connectivity and permissions
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function adminPing() {
  const url = `${API_BASE_URL}/api/admin/_ping`;
  return adminFetch(url, { method: "GET" });
}

/**
 * Get list of all users (admin only)
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getAdminUsers() {
  const url = `${API_BASE_URL}/api/admin/users`;
  return adminFetch(url, { method: "GET" });
}

/**
 * Get timeline debug data for a specific user
 * @param {string} userEmail - User email to debug
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getTimelineDebug(userEmail) {
  if (!userEmail) {
    return {
      success: false,
      data: null,
      error: "User email is required",
      debug: {
        url: null,
        method: 'GET',
        request_id: generateRequestId(),
        duration_ms: 0,
        status: 400,
        timestamp: new Date().toISOString(),
        responseBody: { error: "Missing userEmail parameter" }
      },
      request_id: generateRequestId(),
      duration_ms: 0,
      status: 400,
    };
  }
  const url = `${API_BASE_URL}/api/admin/timeline-debug/${encodeURIComponent(userEmail)}`;
  return adminFetch(url, { method: "GET", ttlMs: 30000 });
}

/**
 * Trigger timeline refresh for a specific user
 * @param {string} userEmail - User email to refresh
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function triggerTimelineRefresh(userEmail) {
  if (!userEmail) {
    return {
      success: false,
      data: null,
      error: "User email is required",
      debug: {
        url: null,
        method: 'POST',
        request_id: generateRequestId(),
        duration_ms: 0,
        status: 400,
        timestamp: new Date().toISOString(),
        responseBody: { error: "Missing userEmail parameter" }
      },
      request_id: generateRequestId(),
      duration_ms: 0,
      status: 400,
    };
  }
  const url = `${API_BASE_URL}/api/admin/timeline-debug/${encodeURIComponent(userEmail)}/refresh`;
  return adminFetch(url, { method: "POST", forceRefresh: true });
}

/**
 * Get VSCode debug data for a specific user
 * @param {string} userEmail - User email to debug
 * @param {string} startDate - Start date (YYYY-MM-DD)
 * @param {string} endDate - End date (YYYY-MM-DD)
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getVSCodeDebug(userEmail, startDate, endDate) {
  if (!userEmail) {
    return {
      success: false,
      data: null,
      error: "User email is required",
      debug: {
        url: null,
        method: 'GET',
        request_id: generateRequestId(),
        duration_ms: 0,
        status: 400,
        timestamp: new Date().toISOString(),
        responseBody: { error: "Missing userEmail parameter" }
      },
      request_id: generateRequestId(),
      duration_ms: 0,
      status: 400,
    };
  }

  const params = new URLSearchParams();
  if (startDate) params.append("start_date", startDate);
  if (endDate) params.append("end_date", endDate);

  const url = `${API_BASE_URL}/api/admin/vscode-debug/${encodeURIComponent(userEmail)}?${params.toString()}`;
  return adminFetch(url, { method: "GET", forceRefresh: true });
}

/**
 * Get collaboration debug data for multiple users
 * @param {string[]} userEmails - Array of user emails (1-4)
 * @param {number} days - Number of days to analyze
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getCollaborationDebug(userEmails, days = 7) {
  if (!userEmails || userEmails.length === 0) {
    return {
      success: false,
      data: null,
      error: "At least one user email is required",
      debug: {
        url: null,
        method: 'GET',
        request_id: generateRequestId(),
        duration_ms: 0,
        status: 400,
        timestamp: new Date().toISOString(),
        responseBody: { error: "Missing userEmails parameter" }
      },
      request_id: generateRequestId(),
      duration_ms: 0,
      status: 400,
    };
  }

  const params = new URLSearchParams();
  userEmails.forEach(email => params.append("users", email));
  params.append("days", days.toString());

  const url = `${API_BASE_URL}/api/admin/collaboration-debug?${params.toString()}`;
  return adminFetch(url, { method: "GET" });
}

/**
 * Get system overview data
 * @param {number} days - Number of days to analyze
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getSystemOverview(days = 7, fetchOptions = {}) {
  const params = new URLSearchParams();
  params.append("days", days.toString());

  const url = `${API_BASE_URL}/api/admin/system-overview?${params.toString()}`;
  return adminFetch(url, { method: "GET", ...fetchOptions });
}

/**
 * Get admin settings
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getAdminSettings() {
  const url = `${API_BASE_URL}/api/admin/settings`;
  return adminFetch(url, { method: "GET" });
}

/**
 * Update admin settings
 * @param {object} settings - Settings payload
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function updateAdminSettings(settings = {}) {
  const url = `${API_BASE_URL}/api/admin/settings`;
  return adminFetch(url, {
    method: "POST",
    body: JSON.stringify(settings),
  });
}

/**
 * Get admin logs
 * @param {string} source - Log source (timeline|admin|auth|etc)
 * @param {number} limit - Max log entries to fetch
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getAdminLogs(source = "timeline", limit = 200, options = {}) {
  const params = new URLSearchParams();
  if (source) params.append("source", source);
  if (limit) params.append("limit", limit.toString());

  const url = `${API_BASE_URL}/api/admin/logs?${params.toString()}`;
  return adminFetch(url, { method: "GET", ...options });
}

/**
 * Write a test log entry
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function writeTestLog() {
  const url = `${API_BASE_URL}/api/admin/logs/test`;
  return adminFetch(url, { method: "POST" });
}

/**
 * Get admin events (activity graph)
 * @param {number} days
 * @param {string[]} users
 * @param {string[]} types
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getAdminEvents(days = 7, users = [], types = [], fetchOptions = {}) {
  const params = new URLSearchParams();
  if (days) params.append("days", days.toString());
  users.forEach((u) => params.append("users", u));
  types.forEach((t) => params.append("types", t));

  const url = `${API_BASE_URL}/api/admin/events?${params.toString()}`;
  return adminFetch(url, { method: "GET", ttlMs: 10000, ...fetchOptions });
}

/**
 * Get detailed stage data
 * @param {string} userEmail
 * @param {string} stageKey
 * @param {number} limit
 * @param {number} page
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getTimelineStageDetails(userEmail, stageKey, limit = 50, page = 1, fetchOptions = {}) {
  if (!userEmail || !stageKey) {
    return {
      success: false,
      data: null,
      error: "User email and stage key are required",
      debug: {
        url: null,
        method: 'GET',
        request_id: generateRequestId(),
        duration_ms: 0,
        status: 400,
        timestamp: new Date().toISOString(),
        responseBody: { error: "Missing params" }
      },
      request_id: generateRequestId(),
      duration_ms: 0,
      status: 400,
    };
  }

  const params = new URLSearchParams();
  if (limit) params.append("limit", limit.toString());
  if (page) params.append("page", page.toString());

  const url = `${API_BASE_URL}/api/admin/timeline-debug/${encodeURIComponent(
    userEmail
  )}/stage/${encodeURIComponent(stageKey)}?${params.toString()}`;
  return adminFetch(url, { method: "GET", forceRefresh: true, ...fetchOptions });
}

/**
 * Get collaboration graph (users/chats/signals)
 */
export async function getCollaborationGraph(users = [], days = 7, depth = 50, includeMessages = true, fetchOptions = {}) {
  const params = new URLSearchParams();
  users.forEach((u) => params.append("users", u));
  params.append("days", days.toString());
  params.append("depth", depth.toString());
  if (includeMessages) params.append("include_messages", "true");
  const url = `${API_BASE_URL}/api/admin/collaboration-graph?${params.toString()}`;
  return adminFetch(url, { method: "GET", ...fetchOptions });
}

/**
 * Run collaboration audit
 */
export async function runCollaborationAudit(body = {}, fetchOptions = {}) {
  const url = `${API_BASE_URL}/api/admin/collaboration-audit/run`;
  const hasBody = Object.keys(body || {}).length > 0;
  return adminFetch(url, {
    method: "POST",
    body: hasBody ? JSON.stringify(body) : undefined,
    ...fetchOptions,
  });
}

/**
 * Get collaboration messages for a user
 * @param {string} userEmail
 * @param {number} limit
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getCollaborationMessages(userEmail, limit = 20) {
  if (!userEmail) {
    return {
      success: false,
      data: null,
      error: "User email is required",
      debug: {
        url: null,
        method: 'GET',
        request_id: generateRequestId(),
        duration_ms: 0,
        status: 400,
        timestamp: new Date().toISOString(),
        responseBody: { error: "Missing user email" }
      },
      request_id: generateRequestId(),
      duration_ms: 0,
      status: 400,
    };
  }
  const params = new URLSearchParams();
  params.append("user_email", userEmail);
  if (limit) params.append("limit", limit.toString());
  const url = `${API_BASE_URL}/api/admin/collaboration/messages?${params.toString()}`;
  return adminFetch(url, { method: "GET" });
}

/**
 * Get list of all organizations (admin only)
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getOrganizations() {
  const url = `${API_BASE_URL}/api/admin/orgs`;
  return adminFetch(url, { method: "GET" });
}

/**
 * Create a new organization (admin only)
 * @param {string} name - Organization name
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function createOrganization(name) {
  if (!name || !name.trim()) {
    return {
      success: false,
      data: null,
      error: "Organization name is required",
      debug: {
        url: null,
        method: 'POST',
        request_id: generateRequestId(),
        duration_ms: 0,
        status: 400,
        timestamp: new Date().toISOString(),
        responseBody: { error: "Missing name parameter" }
      },
      request_id: generateRequestId(),
      duration_ms: 0,
      status: 400,
    };
  }

  const url = `${API_BASE_URL}/api/admin/orgs/create`;
  return adminFetch(url, {
    method: "POST",
    body: JSON.stringify({ name: name.trim() }),
  });
}

/**
 * Get all waitlist submissions (admin only)
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function getWaitlistSubmissions(limit = 50, cursor = null, fetchOptions = {}) {
  const params = new URLSearchParams();
  if (limit) params.append("limit", limit.toString());
  if (cursor) params.append("cursor", cursor);
  const url = `${API_BASE_URL}/api/admin/waitlist?${params.toString()}`;
  return adminFetch(url, { method: "GET", ...fetchOptions });
}

export async function getWaitlistStats(fetchOptions = {}) {
  const url = `${API_BASE_URL}/api/admin/waitlist/stats`;
  return adminFetch(url, { method: "GET", ...fetchOptions });
}

export async function deleteWaitlistSubmission(id, fetchOptions = {}) {
  const url = `${API_BASE_URL}/api/admin/waitlist/${encodeURIComponent(id)}`;
  return adminFetch(url, { method: "DELETE", ...fetchOptions });
}

/**
 * Run admin selftest - tests all critical admin endpoints
 * @returns {Promise<{success: boolean, data: any, error: string|null, debug: object}>}
 */
export async function adminSelftest() {
  const url = `${API_BASE_URL}/api/admin/_selftest`;
  return adminFetch(url, { method: "GET" });
}

/**
 * Helper to format error for display
 * @param {object} error - Error object from adminFetch
 * @returns {string} - Formatted error message for display
 */
export function formatAdminError(error) {
  if (!error) return "Unknown error";

  // If it's a structured admin error
  if (error.status !== undefined) {
    const statusText = getStatusText(error.status);
    let message = `Admin API Error (${error.status})`;
    if (statusText) message += ` - ${statusText}`;
    message += `\n${error.message}`;

    // Add helpful context for common errors
    if (error.status === 401) {
      message += "\n\nYou are not authenticated. Please log in.";
    } else if (error.status === 403) {
      message += "\n\nYou are authenticated but not a platform admin.";
    } else if (error.status === 404) {
      message += "\n\nEndpoint not found. Backend may not be implemented yet.";
    } else if (error.status === 500) {
      message += "\n\nBackend server error. Check backend logs.";
    } else if (error.status === 0) {
      message += "\n\nCannot connect to backend. Is it running?";
    }

    return message;
  }

  // Fallback for other error types
  return error.message || error.toString();
}

/**
 * Get human-readable status text
 * @param {number} status - HTTP status code
 * @returns {string} - Status text
 */
function getStatusText(status) {
  const statusTexts = {
    0: "Network Error",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
  };
  return statusTexts[status] || "";
}
