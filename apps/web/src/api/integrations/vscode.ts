import { API_BASE_URL, config } from "../../config";

const BASE = `${API_BASE_URL}/api/v1/integrations/vscode`;
const OAUTH_BASE = `${API_BASE_URL}/api/v1/oauth`;

// DEV MODE: Skip auth errors and return mock data
const DEV_SKIP_AUTH_ERRORS = config.isDev;

type RequestOptions = {
  method?: string;
  body?: any;
  signal?: AbortSignal;
};

async function request(path: string, options: RequestOptions = {}) {
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: options.method || "GET",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
      signal: options.signal,
      body:
        options.body && typeof options.body === "string"
          ? options.body
          : options.body
          ? JSON.stringify(options.body)
          : undefined,
    });

    if (!res.ok) {
      // In dev mode, treat 401/403 as "not authenticated" and return mock data
      if (DEV_SKIP_AUTH_ERRORS && (res.status === 401 || res.status === 403)) {
        console.warn(`[VSCODE API] Auth error ${res.status} ignored in dev mode for ${path}`);
        return { connected: false, sessions: [] };
      }
      
      const text = await res.text().catch(() => res.statusText);
      const error = new Error(text || "Request failed");
      // @ts-expect-error augment for runtime inspection
      error.status = res.status;
      throw error;
    }

    if (res.status === 204) return null;

    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return res.json();
    }

    return res.text();
  } catch (err: any) {
    // Network errors in dev mode
    if (DEV_SKIP_AUTH_ERRORS && (err.message?.includes('Failed to fetch') || err.name === 'TypeError')) {
      console.warn(`[VSCODE API] Network error ignored in dev mode for ${path}:`, err.message);
      return { connected: false, sessions: [] };
    }
    throw err;
  }
}

export function getStatus(signal?: AbortSignal) {
  return request("/status", { signal });
}

export function startConnect() {
  return request("/connect/start", { method: "POST" });
}

export function createToken() {
  return request("/tokens", { method: "POST" });
}

export function listSessions() {
  return request("/sessions");
}

export function revokeSession(id: string) {
  return request(`/sessions/${id}/revoke`, { method: "POST" });
}

export function disconnectAll() {
  return request("/disconnect", { method: "POST" }).catch(async (err: any) => {
    if (err?.status === 404) {
      try {
        return await request("/sessions/revoke-all", { method: "POST" });
      } catch (fallbackErr: any) {
        const combinedMessage =
          fallbackErr?.message ||
          `Disconnect failed via both endpoints (primary ${err?.status || "error"})`;
        const error = new Error(combinedMessage);
        // @ts-expect-error enrich error object for runtime checks
        error.status = fallbackErr?.status || err?.status;
        throw error;
      }
    }
    throw err;
  });
}

export function savePreferences(payload: Record<string, any>) {
  return request("/preferences", { method: "POST", body: payload });
}

// OAuth endpoints for VS Code extension authorization

type OAuthRequestOptions = {
  method?: string;
  body?: any;
};

async function oauthRequest(path: string, options: OAuthRequestOptions = {}) {
  try {
    const res = await fetch(`${OAUTH_BASE}${path}`, {
      method: options.method || "GET",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      const error = new Error(text || "OAuth request failed");
      // @ts-expect-error augment for runtime inspection
      error.status = res.status;
      throw error;
    }

    if (res.status === 204) return null;

    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return res.json();
    }

    return res.text();
  } catch (err: any) {
    throw err;
  }
}

/**
 * Submit OAuth authorization approval
 */
export function submitOAuthApproval(params: {
  client_id: string;
  redirect_uri?: string;
  state?: string;
  scope?: string;
  response_type?: string;
  approved: boolean;
}) {
  return oauthRequest("/authorize", { method: "POST", body: params });
}

/**
 * Revoke an OAuth token/session
 */
export function revokeOAuthToken(tokenId: string) {
  return oauthRequest(`/revoke`, { method: "POST", body: { token_id: tokenId } });
}

/**
 * List all active OAuth sessions/tokens for the current user
 */
export function listOAuthSessions() {
  return oauthRequest("/sessions");
}
