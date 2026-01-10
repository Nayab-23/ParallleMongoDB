import { API_BASE_URL } from "../config";

const APPS_BASE = `${API_BASE_URL}/api/oauth`;
const LEGACY_OAUTH_BASE = `${API_BASE_URL}/api/v1/oauth`;

type RequestOptions = {
  method?: string;
  body?: any;
};

async function requestJson(url: string, options: RequestOptions = {}) {
  const res = await fetch(url, {
    method: options.method || "GET",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    const error = new Error(text || "Request failed");
    // @ts-expect-error augment error with status for callers
    error.status = res.status;
    throw error;
  }

  if (res.status === 204) return null;

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return res.json();
  }

  return res.text();
}

export async function listOAuthApps() {
  try {
    return await requestJson(`${APPS_BASE}/apps`);
  } catch (err: any) {
    if (err?.status === 404) {
      return requestJson(`${LEGACY_OAUTH_BASE}/sessions`);
    }
    throw err;
  }
}

export async function revokeOAuthApp(appId: string) {
  try {
    return await requestJson(`${APPS_BASE}/apps/revoke`, {
      method: "POST",
      body: { id: appId, app_id: appId, session_id: appId },
    });
  } catch (err: any) {
    if (err?.status === 404) {
      return requestJson(`${LEGACY_OAUTH_BASE}/revoke`, {
        method: "POST",
        body: { token_id: appId },
      });
    }
    throw err;
  }
}
