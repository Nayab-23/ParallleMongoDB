import { API_BASE_URL } from "../config";
import { loggedFetch } from "../lib/apiLogger";

async function request(path, options = {}) {
  const url = `${API_BASE_URL}${path}`;
  const res = await loggedFetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    const error = new Error(body || `Request failed (${res.status})`);
    error.status = res.status;
    error.body = body;
    throw error;
  }

  if (res.status === 204) {
    return null;
  }

  return res.json();
}

export function getMe() {
  return request("/api/me");
}

export function listChats({ limit = 50, cursor } = {}) {
  const params = new URLSearchParams();
  if (limit) params.set("limit", String(limit));
  if (cursor) params.set("cursor", cursor);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request(`/api/chats${suffix}`);
}

export function createChat(name) {
  return request("/api/chats", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function getChatMessages(chatId, { limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (limit) params.set("limit", String(limit));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request(`/api/chats/${chatId}/messages${suffix}`);
}

export function dispatchChat(chatId, content) {
  return request(`/api/chats/${chatId}/dispatch`, {
    method: "POST",
    body: JSON.stringify({ mode: "vscode", content }),
  });
}

export function getTaskStatus(taskId) {
  return request(`/api/v1/extension/tasks/${taskId}`);
}
