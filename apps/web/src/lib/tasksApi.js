// Simple API adapter for tasks + team info + rooms + memberships
import { API_BASE_URL } from "../config";
import { logger } from "../utils/logger";

// DEV MODE: Skip auth errors and return mock data
// IMPORTANT: Set to false to enable proper authentication flow
const DEV_SKIP_AUTH_ERRORS = false;

// Always use backend (manager features)
async function j(path, opts = {}, timeout = 30000) {
  const url = `${API_BASE_URL}/api${path}`;
  logger.debug(`[API] ${opts.method || "GET"} ${url}`);

  // Create AbortController for timeout
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    logger.warn(`[API] Request timeout after ${timeout}ms for ${path}`);
    controller.abort();
  }, timeout);

  const startTime = Date.now();

  try {
    const res = await fetch(url, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...opts,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);
    const elapsed = Date.now() - startTime;

    // Warn about slow requests (>3s in dev mode)
    if (DEV_SKIP_AUTH_ERRORS && elapsed > 3000) {
      logger.warn(`[API] ⚠️ SLOW REQUEST: ${path} took ${elapsed}ms`);
    }

    logger.debug(`[API] Response status: ${res.status} ${res.statusText} (${elapsed}ms)`);

    if (!res.ok) {
      // In dev mode, treat 401/403 as "not authenticated" and return null
      if (DEV_SKIP_AUTH_ERRORS && (res.status === 401 || res.status === 403)) {
        logger.warn(`[API] Auth error ${res.status} ignored in dev mode for ${path}`);
        return null;
      }

      const errorText = await res.text().catch(() => res.statusText);
      logger.error(`[API] Error response (${res.status}): ${errorText}`);
      const error = new Error(`${res.status}: ${errorText}`);
      error.status = res.status;
      error.body = errorText;
      error.url = url;
      throw error;
    }

    if (res.status === 204) {
      logger.debug("[API] No content (204)");
      return null;
    }

    const data = await res.json();
    logger.debug("[API] Response data:", data);
    return data;
  } catch (err) {
    clearTimeout(timeoutId);

    // Handle timeout errors
    if (err.name === 'AbortError') {
      const timeoutError = new Error(`Request timeout after ${timeout}ms`);
      timeoutError.status = 0;
      timeoutError.timeout = true;
      timeoutError.url = url;
      logger.error(`[API] ⏱️ Timeout for ${path} after ${timeout}ms`);

      // In dev mode, return null for timeouts
      if (DEV_SKIP_AUTH_ERRORS) {
        logger.warn(`[API] Timeout ignored in dev mode for ${path}`);
        return null;
      }

      throw timeoutError;
    }

    // Network errors or other failures in dev mode
    if (
      DEV_SKIP_AUTH_ERRORS &&
      (err.message?.includes("401") ||
        err.message?.includes("403") ||
        err.message?.includes("Failed to fetch"))
    ) {
      logger.warn(`[API] Error ignored in dev mode for ${path}:`, err.message);
      return null;
    }
    throw err;
  }
}

function normalizeChat(raw) {
  if (!raw || typeof raw !== "object") return null;
  const chatId = raw.chat_id || raw.id || raw.chatId || raw.uuid;
  const roomIds = Array.isArray(raw.room_ids)
    ? raw.room_ids.filter(Boolean)
    : raw.room_id
    ? [raw.room_id]
    : [];
  return {
    ...raw,
    id: chatId || raw.id || raw.chat_id,
    chat_id: chatId || raw.chat_id || raw.id,
    name: raw.name || raw.chat_name || raw.title || "Chat",
    room_id: raw.room_id || raw.roomId || raw.room,
    room_ids: roomIds,
    last_message_at:
      raw.last_message_at ||
      raw.lastMessageAt ||
      raw.updated_at ||
      raw.updatedAt ||
      raw.last_message,
  };
}

// ---- Team ----
export async function fetchTeam() {
  try {
    const data = await j(`/v1/users`);
    // Handle both array response and object with users property
    if (Array.isArray(data)) {
      return data;
    }
    if (data && Array.isArray(data.users)) {
      return data.users;
    }
    console.warn("[fetchTeam] Unexpected response format:", data);
    return [];
  } catch (err) {
    console.error("[fetchTeam] Failed:", err);
    // Mock so UI runs immediately
    return [
      { id: "u1", name: "You", roles: ["Coordinator"], status: "active" },
      { id: "u2", name: "Researcher", roles: ["Analysis"], status: "idle" },
      { id: "u3", name: "Engineer", roles: ["Implementation"], status: "active" },
    ];
  }
}

// ---- Tasks ----
export async function listTasks() {
  try {
    const data = await j(`/tasks`);
    return data || [];
  } catch {
    return [];
  }
}

export async function createTask({ title, description, assignee_id }) {
  try {
    return await j(`/tasks`, {
      method: "POST",
      body: JSON.stringify({ title, description, assignee_id }),
    });
  } catch {
    // Fallback: pretend created
    return {
      id: String(Date.now()),
      title,
      description,
      assignee_id,
      status: "new",
      created_at: new Date().toISOString(),
    };
  }
}

export async function updateTaskStatus(taskId, status) {
  try {
    return await j(`/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
  } catch {
    return { id: taskId, status };
  }
}

export async function updateUserRole(userId, role) {
  return j(`/users/${userId}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

// ---- Notifications (assignee inbox) ----
export async function listMyNotifications(userId) {
  try {
    const data = await j(`/users/${userId}/notifications`);
    return data || [];
  } catch {
    return [];
  }
}

export async function pushTaskNotification({ assignee_id, task }) {
  try {
    await j(`/users/${assignee_id}/notifications`, {
      method: "POST",
      body: JSON.stringify({
        type: "task_assigned",
        task_id: task.id,
        title: task.title,
        message: task.description,
      }),
    });
  } catch {
    // no-op if backend not ready
  }
}

// ---- Rooms ----
export async function listRooms() {
  try {
    const data = await j(`/v1/rooms`);
    // Handle both array response and object with rooms/workspaces property
    if (Array.isArray(data)) {
      return data;
    }
    if (data && Array.isArray(data.rooms)) {
      return data.rooms;
    }
    if (data && Array.isArray(data.workspaces)) {
      return data.workspaces;
    }
    console.warn("[listRooms] Unexpected response format:", data);
    return [];
  } catch (err) {
    console.error("[listRooms] Failed:", err);
    return [];
  }
}

// New: list all chats (room-agnostic)
// export async function listAllChats() {
//   try {
//     console.log("📡 [listAllChats] Calling /chats endpoint...");
//     const data = await j(`/chats`);
//     console.log("📡 [listAllChats] Raw response:", data);
//     console.log("📡 [listAllChats] Has chats key?", data?.chats !== undefined);
//     console.log("📡 [listAllChats] Chats array:", data?.chats);
//     return data?.chats || [];
//   } catch (err) {
//     console.error("❌ [listAllChats] Error:", err);
//     console.error("❌ [listAllChats] Error details:", err.message, err.stack);
//     throw err;  // THROW instead of returning empty array so we see the error
//   }
// }

/**
 * List all chats for a workspace
 * @param {string} workspaceId - The workspace UUID
 * @param {object} options - Optional parameters
 * @param {string} options.cursor - Pagination cursor
 * @param {number} options.limit - Number of chats to return (default: 50)
 * @param {string} options.updatedAfter - ISO timestamp filter
 * @returns {Promise<Array>} Array of normalized chat objects
 */
export async function listAllChats(workspaceId, options = {}) {
  try {
    const { cursor, limit = 50, updatedAfter, useGlobal } = options;

    console.log("🔍 [listAllChats] Starting", { workspaceId, cursor, limit, updatedAfter });

    // Global cross-room endpoint (new)
    if (useGlobal) {
      const params = new URLSearchParams();
      if (cursor) params.append("cursor", cursor);
      if (limit) params.append("limit", limit.toString());
      const endpoint = `/v1/chats${params.toString() ? `?${params.toString()}` : ""}`;
      console.log("📡 [listAllChats] Using global endpoint:", endpoint);
      const data = await j(endpoint);
      if (data === null) return { items: [], next_cursor: null };
      const rawList = Array.isArray(data?.items)
        ? data.items
        : Array.isArray(data)
        ? data
        : Array.isArray(data?.data?.items)
        ? data.data.items
        : [];
      const nextCursor = data?.next_cursor || data?.data?.next_cursor || null;
      console.log("📊 [listAllChats] Global raw item count:", rawList.length, "next_cursor:", nextCursor);
      const items = rawList
        .map((item, idx) => {
          const n = normalizeChat(item);
          console.log("🔧 [listAllChats] Global normalize", idx, { id: n?.id || n?.chat_id, room_ids: n?.room_ids });
          return n;
        })
        .filter(Boolean);
      console.log(`📡 [listAllChats] Global loaded ${items.length} chats`);
      return { items, next_cursor: nextCursor };
    }

    // If no workspaceId provided, try the old endpoint for backwards compatibility
    if (!workspaceId) {
      console.warn("📡 [listAllChats] No workspaceId provided, using legacy /chats endpoint");
      const data = await j(`/chats`);

      if (data === null) {
        return { items: [], next_cursor: null };
      }

      const rawList = Array.isArray(data)
        ? data
        : Array.isArray(data?.chats)
        ? data.chats
        : Array.isArray(data?.items)
        ? data.items
        : Array.isArray(data?.data?.items)
        ? data.data.items
        : [];
      const nextCursor = data?.next_cursor || data?.data?.next_cursor || null;
      console.log("📥 [listAllChats] Legacy raw length:", rawList.length, "next_cursor:", nextCursor);
      const items = rawList.map(normalizeChat).filter(Boolean);
      return { items, next_cursor: nextCursor };
    }

    // Build query parameters
    const params = new URLSearchParams();
    if (cursor) params.append('cursor', cursor);
    if (limit) params.append('limit', limit.toString());
    if (updatedAfter) params.append('updated_after', updatedAfter);

    const queryString = params.toString();
    const endpoint = `/v1/workspaces/${workspaceId}/chats${queryString ? '?' + queryString : ''}`;

    console.log(`📡 [listAllChats] Fetching chats for workspace ${workspaceId}`);
    console.log(`📡 [listAllChats] Endpoint: ${endpoint}`);

    const data = await j(endpoint);
    console.log("📡 [listAllChats] Raw response:", data);

    // If null (auth skipped in dev mode), return empty array
    if (data === null) {
      console.log("📡 [listAllChats] No data (dev mode), returning empty array");
      return { items: [], next_cursor: null };
    }

    // Handle {"items": [...]}, {"chats": [...]}, and bare array
    const itemsArray = Array.isArray(data)
      ? data
      : Array.isArray(data?.items)
      ? data.items
      : Array.isArray(data?.chats)
      ? data.chats
      : Array.isArray(data?.data?.items)
      ? data.data.items
      : [];
    const nextCursor = data?.next_cursor || data?.data?.next_cursor || null;

    console.log("📊 [listAllChats] Raw item count:", itemsArray.length);
    const items = itemsArray
      .map((item, idx) => {
        const n = normalizeChat(item);
        console.log("🔧 [listAllChats] Normalizing item", idx, { id: n?.id || n?.chat_id, type: n?.type, name: n?.name, room_ids: n?.room_ids });
        return n;
      })
      .filter(Boolean);
    console.log(`📡 [listAllChats] Loaded ${items.length} chats`, items.map((c) => c.id || c.chat_id));

    return { items, next_cursor: nextCursor };
  } catch (err) {
    console.error("❌ [listAllChats] Error:", err);
    console.error("❌ [listAllChats] Error details:", err.message, err.stack);
    // Return empty array instead of throwing in case of any error
    return { items: [], next_cursor: null };
  }
}

// Update chat room access list (cross-room binding)
export async function updateChatRooms(chatId, roomIds = []) {
  try {
    const body = { room_ids: Array.isArray(roomIds) ? roomIds : [] };
    const data = await j(`/v1/chats/${chatId}/rooms`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    return data;
  } catch (err) {
    console.error("❌ [updateChatRooms] Error:", err);
    return null;
  }
}

// New: create chat (backend assigns room)
export async function createChat(chatName) {
  try {
    const data = await j(`/chats`, {
      method: "POST",
      body: JSON.stringify({ name: chatName }),
    });
    
    // If null (auth skipped in dev mode), return mock chat
    if (data === null) {
      // console.log("[API] createChat: Auth skipped, returning mock chat");
      return {
        id: `dev-chat-${Date.now()}`,
        chat_id: `dev-chat-${Date.now()}`,
        name: chatName,
        room_id: null,
      };
    }
    
    return normalizeChat(data) || data;
  } catch (err) {
    console.error("Failed to create chat:", {
      status: err?.status,
      body: err?.body,
      message: err?.message,
      url: err?.url,
    });
    // Return mock chat instead of throwing
    return {
      id: `dev-chat-${Date.now()}`,
      chat_id: `dev-chat-${Date.now()}`,
      name: chatName,
      room_id: null,
    };
  }
}

// Rename chat
export async function renameChat(chatId, name) {
  try {
    const data = await j(`/chats/${chatId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
    return data;
  } catch (err) {
    console.error("Failed to rename chat:", err);
    throw err;
  }
}

// Delete chat
export async function deleteChat(chatId) {
  try {
    await j(`/chats/${chatId}`, { method: "DELETE" });
    return true;
  } catch (err) {
    console.error("Failed to delete chat:", err);
    throw err;
  }
}

// Legacy room helpers (still used by Manager/RoomContext)
export async function createRoom(roomName) {
  try {
    const data = await j(`/rooms`, {
      method: "POST",
      body: JSON.stringify({ room_name: roomName }),
    });
    return data;
  } catch (err) {
    console.error("Failed to create room:", err);
    throw err;
  }
}

export async function deleteRoom(roomId) {
  try {
    await j(`/rooms/${roomId}`, {
      method: "DELETE",
    });
    return true;
  } catch (err) {
    console.error("Failed to delete room:", err);
    throw err;
  }
}

export async function getRoomDetails(roomId) {
  try {
    const data = await j(`/rooms/${roomId}`);
    return data;
  } catch (err) {
    console.error("Failed to get room details:", err);
    throw err;
  } // adasa
}

// Org graph data
export async function getOrgGraphData(workspaceId = 1) {
  console.log('[API] getOrgGraphData called with workspaceId:', workspaceId);
  const url = `${API_BASE_URL}/api/v1/workspaces/${workspaceId}/org-graph`;
  console.log('[API] Full URL:', url);

  const startTime = Date.now();
  const res = await fetch(url, {
    credentials: "include",
  });

  const elapsed = Date.now() - startTime;
  console.log(`[API] getOrgGraphData response in ${elapsed}ms with status:`, res.status);

  if (!res.ok) {
    const errText = await res.text().catch(() => "");
    console.error('[API] getOrgGraphData failed:', {
      status: res.status,
      statusText: res.statusText,
      errorBody: errText,
      url
    });
    throw new Error(`Failed to fetch org graph (${res.status}): ${errText}`);
  }

  const data = await res.json();
  console.log('[API] getOrgGraphData success, data structure:', {
    hasRooms: !!data?.rooms,
    roomCount: data?.rooms?.length || 0,
    hasEdges: !!data?.edges,
    edgeCount: data?.edges?.length || 0,
    hasMembers: !!data?.members,
    memberCount: Object.keys(data?.members || {}).length,
    fullData: data
  });
  return data;
}

// ---- Timeline ----
export async function getTimeline() {
  const res = await fetch(`${API_BASE_URL}/api/v1/users/me/timeline`, {
    credentials: "include",
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => "");
    throw new Error(`Failed to fetch timeline (${res.status}): ${errText}`);
  }

  return res.json();
}

// ---- Room Membership ----
export async function getUserRooms(userId) {
  try {
    return await j(`/users/${userId}/rooms`);
  } catch (err) {
    console.error("Failed to get user rooms:", err);
    return [];
  }
}

export async function updateUserRooms(userId, roomIds) {
  try {
    return await j(`/users/${userId}/rooms`, {
      method: "PUT",
      body: JSON.stringify({ room_ids: roomIds }),
    });
  } catch (err) {
    console.error("Failed to update user rooms:", err);
    throw err;
  }
}

export async function addRoomMember(roomId, userId, roleInRoom = null) {
  try {
    return await j(`/rooms/${roomId}/members`, {
      method: "POST",
      body: JSON.stringify({
        room_id: roomId,
        user_id: userId,
        role_in_room: roleInRoom,
      }),
    });
  } catch (err) {
    console.error("Failed to add room member:", err);
    throw err;
  }
}

export async function removeRoomMember(roomId, userId) {
  try {
    await j(`/rooms/${roomId}/members/${userId}`, {
      method: "DELETE",
    });
    return true;
  } catch (err) {
    console.error("Failed to remove room member:", err);
    throw err;
  }
}

export async function getRoomMembers(roomId) {
  try {
    return await j(`/rooms/${roomId}/members`);
  } catch (err) {
    console.error("Failed to get room members:", err);
    return [];
  }
}

// ---- Room chats ----
export async function listRoomChats(roomId) {
  try {
    return await j(`/rooms/${roomId}/chats`);
  } catch (err) {
    console.error("Failed to list room chats:", err);
    return [];
  }
}

export async function createRoomChat(roomId, name) {
  // console.group("🔷 [API] createRoomChat");
  // console.log("Room ID:", roomId);
  // console.log("Chat name:", name);
  // console.log("API Base URL:", API_BASE_URL);

  const url = `${API_BASE_URL}/api/rooms/${roomId}/chats`;
  // console.log("Full URL:", url);

  const payload = { name };
  // console.log("Payload:", JSON.stringify(payload, null, 2));

  try {
    const response = await j(`/rooms/${roomId}/chats`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    logger.debug("✅ API Success");
    logger.debug("Response:", response);
    logger.debug("Response type:", typeof response);
    logger.debug("Response keys:", Object.keys(response || {}));
    console.groupEnd();

    return response;
  } catch (err) {
    logger.error("❌ API Error");
    logger.error("Error:", err);
    logger.error("Error message:", err.message);
    console.groupEnd();
    throw err;
  }
}

export async function getChatMessages(chatId) {
  logger.debug("[API] getChatMessages:", chatId);
  try {
    const data = await j(`/chats/${chatId}/messages`);
    
    // If null (auth skipped in dev mode), return empty array
    if (data === null) {
      console.log("[API] getChatMessages: No data (dev mode), returning empty array");
      return [];
    }
    
    const messages = Array.isArray(data)
      ? data
      : Array.isArray(data?.messages)
      ? data.messages
      : [];
    logger.debug("[API] getChatMessages response:", {
      count: messages.length,
    });
    return messages;
  } catch (err) {
    logger.error("[API] getChatMessages failed:", err);
    throw err;
  }
}

/**
 * Send a message to a chat
 * Always posts to /api/chats/{chatId}/ask with context preview flag
 */
export async function askInChat(chatId, payload = {}, opts = {}) {
  if (!chatId) throw new Error("chatId is required for askInChat");
  const url = `${API_BASE_URL}/api/chats/${chatId}/ask`;

  if (import.meta.env?.DEV) {
    if (url.includes("/api/rooms/") || url.includes("/messages") || url.includes("/api/v1/chats/")) {
      console.error("[ChatSend] Unexpected legacy send route", url);
    }
  }

  const requestId = crypto.randomUUID();
  const controller = new AbortController();
  const envTimeout = Number(import.meta.env?.VITE_CHAT_TIMEOUT_MS);
  const timeoutMs = Number.isFinite(envTimeout) && envTimeout > 0 ? envTimeout : (opts.timeoutMs || 20000);
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  const start = Date.now();
  const clientRequestId = `web-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;

  try {
    const res = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-Request-Id": requestId,
        "X-Client-Request-Id": clientRequestId,
        ...(opts.headers || {}),
      },
      body: JSON.stringify({
        ...payload,
        include_context_preview: opts.includeContextPreview === false ? false : true,
      }),
      signal: controller.signal,
    });

    clearTimeout(timeout);

    const serverRequestId = res.headers.get("X-Request-Id");

    console.info(
      JSON.stringify({
        at: "ChatSend",
        client_request_id: clientRequestId,
        server_request_id: serverRequestId || requestId,
        chat_id: chatId,
        status: res.status,
        elapsed_ms: Date.now() - start,
      })
    );

    const contentType = res.headers.get("content-type") || "";
    if (!res.ok) {
      let bodyText = "";
      try {
        if (contentType.includes("application/json")) {
          const errJson = await res.json();
          bodyText = JSON.stringify(errJson);
          if (errJson?.request_id) {
            console.error("[ChatSend] backend request_id", errJson.request_id);
          }
        } else {
          bodyText = await res.text();
        }
      } catch {
        // ignore parse errors
      }

      console.error("[ChatSend] Non-OK response", {
        status: res.status,
        statusText: res.statusText,
        contentType,
        bodyPreview: (bodyText || "").slice(0, 500),
        request_id: requestId,
        echoed_request_id: serverRequestId,
        client_request_id: clientRequestId,
      });

      const error = new Error(`Ask failed (${res.status}): ${bodyText || res.statusText}`);
      error.diagnostics = {
        classification: "HTTP_ERROR",
        status: res.status,
        statusText: res.statusText,
        contentType,
        bodyPreview: (bodyText || "").slice(0, 300),
        client_request_id: clientRequestId,
        server_request_id: serverRequestId || requestId,
        elapsed_ms: Date.now() - start,
      };
      throw error;
    }

    if (contentType.includes("application/json")) {
      const data = await res.json();
      return {
        data,
        diagnostics: {
          classification: "OK",
          status: res.status,
          contentType,
          client_request_id: clientRequestId,
          server_request_id: serverRequestId || requestId,
          elapsed_ms: Date.now() - start,
        },
      };
    }

    const text = await res.text().catch(() => "");
    return {
      data: { message: text || "No response", context_preview: null },
      diagnostics: {
        classification: "NON_JSON",
        status: res.status,
        contentType,
        bodyPreview: (text || "").slice(0, 300),
        client_request_id: clientRequestId,
        server_request_id: serverRequestId || requestId,
        elapsed_ms: Date.now() - start,
      },
    };
  } catch (err) {
    clearTimeout(timeout);
    const isAbort = err?.name === "AbortError";
    const diag = {
      classification: isAbort ? "TIMEOUT" : err?.name === "TypeError" ? "NETWORK_OR_CORS" : "FETCH_ERROR",
      url,
      method: "POST",
      credentials: "include",
      origin: typeof window !== "undefined" ? window.location.origin : "unknown",
      userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "unknown",
      online: typeof navigator !== "undefined" ? navigator.onLine : "unknown",
      errorName: err?.name,
      errorMessage: err?.message,
      stack: err?.stack,
      timeoutMs,
      elapsedMs: Date.now() - start,
      isAbort,
      client_request_id: clientRequestId,
      server_request_id: requestId,
    };
    console.error("[ChatSend] Error sending message", diag);
    const wrapped = new Error(err?.message || "Request failed");
    wrapped.diagnostics = diag;
    throw wrapped;
  }
}

// Resolve the agent for a given user (auto-creates if missing)
export async function getUserAgent(userId) {
  logger.debug("[API] getUserAgent:", userId);
  try {
    const data = await j(`/users/${userId}/agent`);
    logger.debug("[API] getUserAgent response:", data);
    return data;
  } catch (err) {
    logger.error("[API] getUserAgent failed:", err);
    throw err;
  }
}

// ---- Inbox ----
export async function updateInboxTask(userId, taskId, payload) {
  try {
    return await j(`/users/${userId}/inbox/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  } catch (err) {
    console.error("Failed to update inbox task:", err);
    throw err;
  }
}

// ---- Org + admin helpers ----
export async function joinOrganization(inviteCode) {
  try {
    return await j(`/org/join`, {
      method: "POST",
      body: JSON.stringify({ invite_code: inviteCode }),
    });
  } catch (err) {
    console.error("Failed to join organization:", err);
    throw err;
  }
}

export async function createOrganization(name) {
  try {
    return await j(`/admin/orgs/create`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  } catch (err) {
    console.error("Failed to create organization:", err);
    throw err;
  }
}

export async function listOrganizations() {
  try {
    return await j(`/admin/orgs`);
  } catch (err) {
    console.error("Failed to list organizations:", err);
    return [];
  }
}

// ---- Integrations ----
export async function getIntegrationsStatus() {
  try {
    return await j(`/integrations/status`);
  } catch (err) {
    console.warn("[API] Integrations status failed (non-critical):", err);
    // Return null instead of throwing - don't block page load
    return null;
  }
}

export async function disconnectIntegration(provider) {
  const map = {
    gmail: "/integrations/google_gmail",
    calendar: "/integrations/google_calendar",
  };
  const path = map[provider];
  if (!path) throw new Error("Unknown provider");

  try {
    return await j(path, { method: "DELETE" });
  } catch (err) {
    console.error(`Failed to disconnect ${provider}:`, err);
    throw err;
  }
}

export async function setCanonRefreshInterval(intervalMinutes) {
  const res = await fetch(`${API_BASE_URL}/api/settings/canon-refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ interval_minutes: intervalMinutes }),
  });

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const message =
      detail?.message ||
      detail?.error ||
      detail?.detail ||
      "Failed to update interval";
    throw new Error(message);
  }

  return res.json();
}

// ---- Brief history (completed / deleted items) ----
export async function fetchBriefHistory({ action = "all", limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (action) params.set("action", action);
  if (limit) params.set("limit", String(limit));

  try {
    return await j(`/brief/items/history?${params.toString()}`);
  } catch (err) {
    console.error("Failed to fetch brief history:", err);
    throw err;
  }
}

// ---- Extension tasks ----
function makeClientRequestId() {
  return `web-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

export async function sendExtensionTask(payload = {}) {
  const url = `${API_BASE_URL}/api/v1/extension/send-task`;
  const reqId = makeClientRequestId();
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Client-Request-Id": reqId,
    },
    body: JSON.stringify(payload),
  });

  const ct = res.headers.get("content-type") || "";
  const serverReqId = res.headers.get("X-Request-Id");
  const baseDiag = {
    client_request_id: reqId,
    server_request_id: serverReqId,
    status: res.status,
  };

  if (!res.ok) {
    let bodyText = "";
    try {
      bodyText = await res.text();
    } catch {
      // ignore
    }
    const err = new Error(`Send-task failed (${res.status})`);
    err.diagnostics = { ...baseDiag, body: bodyText };
    throw err;
  }

  if (ct.includes("application/json")) {
    const data = await res.json();
    return { data, diagnostics: baseDiag };
  }
  const text = await res.text().catch(() => "");
  return { data: { message: text }, diagnostics: baseDiag };
}

export async function listExtensionClients() {
  const url = `${API_BASE_URL}/api/v1/extension/clients`;
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to list extension clients (${res.status}): ${text}`);
  }
  return res.json();
}

// Dispatch chat (e.g., VS Code mode)
export async function dispatchChat(chatId, payload = {}) {
  if (!chatId) throw new Error("chatId is required for dispatchChat");
  const url = `${API_BASE_URL}/api/chats/${chatId}/dispatch`;
  const reqId = makeClientRequestId();

  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Client-Request-Id": reqId,
    },
    body: JSON.stringify(payload),
  });

  const ct = res.headers.get("content-type") || "";
  const serverReqId = res.headers.get("X-Request-Id");
  const diagnostics = {
    client_request_id: reqId,
    server_request_id: serverReqId,
    status: res.status,
  };

  if (!res.ok) {
    let body = "";
    try {
      body = await res.text();
    } catch {
      // ignore
    }
    const err = new Error(`Dispatch failed (${res.status})`);
    err.diagnostics = { ...diagnostics, body };
    throw err;
  }

  if (ct.includes("application/json")) {
    const data = await res.json();
    return { data, diagnostics };
  }
  const text = await res.text().catch(() => "");
  return { data: { message: text }, diagnostics };
}

export async function getTaskStatus(taskId) {
  const url = `${API_BASE_URL}/api/v1/extension/tasks/${taskId}`;
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const err = new Error(`Task status failed (${res.status})`);
    err.diagnostics = { status: res.status, body: text };
    throw err;
  }
  return res.json();
}

// Alias for clarity in VS Code dispatch flow
export const getExtensionTask = getTaskStatus;

/**
 * Send a lightweight notification task to the VS Code extension.
 * Returns { ok, data?, error_code?, diagnostics? } without throwing.
 */
export async function sendExtensionNotify(payload = {}, repo_id = null) {
  const url = `${API_BASE_URL}/api/v1/extension/send-task`;
  const reqId = makeClientRequestId();

  try {
    const res = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-Client-Request-Id": reqId,
      },
      body: JSON.stringify({
        task_type: "NOTIFY",
        repo_id: repo_id || undefined,
        payload,
      }),
    });

    const serverReqId = res.headers.get("X-Request-Id");
    const diagnostics = {
      client_request_id: reqId,
      server_request_id: serverReqId,
      status: res.status,
    };

    if (!res.ok) {
      let body = "";
      try {
        body = await res.text();
      } catch {
        // ignore
      }
      return {
        ok: false,
        error_code: "HTTP_ERROR",
        diagnostics: { ...diagnostics, body },
      };
    }

    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      data = await res.json().catch(() => null);
    } else {
      data = { message: await res.text().catch(() => "") };
    }

    if (data?.error_code) {
      return { ok: false, error_code: data.error_code, diagnostics, data };
    }

    return { ok: true, data, diagnostics };
  } catch (err) {
    return {
      ok: false,
      error_code: err?.message || "UNKNOWN",
      diagnostics: { client_request_id: reqId },
    };
  }
}

/**
 * Get recent code activity events for a repository
 * Used to enrich context_brief when dispatching VS Code tasks
 *
 * @param {string} repo_id - Repository ID to fetch events for
 * @param {number} minutes - Time window in minutes (default: 60)
 * @returns {Promise<Array>} Array of code event objects
 */
export async function getRecentCodeEvents(repo_id, minutes = 60) {
  if (!repo_id) {
    throw new Error("repo_id is required for getRecentCodeEvents");
  }

  const params = new URLSearchParams();
  params.set("repo_id", repo_id);
  params.set("minutes", minutes.toString());

  const url = `${API_BASE_URL}/api/v1/code-events/recent?${params.toString()}`;

  try {
    const res = await fetch(url, {
      method: "GET",
      credentials: "include",
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      const err = new Error(`Failed to fetch code events (${res.status})`);
      err.diagnostics = { status: res.status, body: text };
      throw err;
    }

    const data = await res.json();
    // Return events array, limiting to 10 most recent
    const events = data?.events || data?.items || data || [];
    return Array.isArray(events) ? events.slice(0, 10) : [];
  } catch (err) {
    console.error("[CodeEvents] Failed to fetch recent events:", err);
    // Return empty array on error so dispatch can continue
    return [];
  }
}

/**
 * Get conflict-prone code events (events where multiple users edited same systems)
 * Returns matching events (overlap), not aggregated conflict objects
 *
 * @param {string} repo_id - Repository ID to fetch conflicts for
 * @param {Array<string>} systems - Optional array of system names to check
 * @returns {Promise<Array>} Array of overlapping code event objects
 */
export async function getConflictCodeEvents(repo_id, systems = []) {
  if (!repo_id) {
    throw new Error("repo_id is required for getConflictCodeEvents");
  }

  const params = new URLSearchParams();
  params.set("repo_id", repo_id);
  if (Array.isArray(systems) && systems.length > 0) {
    systems.forEach(sys => params.append("systems", sys));
  }

  const url = `${API_BASE_URL}/api/v1/code-events/conflicts?${params.toString()}`;

  try {
    const res = await fetch(url, {
      method: "GET",
      credentials: "include",
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      const err = new Error(`Failed to fetch conflict events (${res.status})`);
      err.diagnostics = { status: res.status, body: text };
      throw err;
    }

    const data = await res.json();
    // Return conflicts array
    const conflicts = data?.conflicts || data?.items || data || [];
    return Array.isArray(conflicts) ? conflicts : [];
  } catch (err) {
    console.error("[CodeEvents] Failed to fetch conflict events:", err);
    // Return empty array on error so dispatch can continue
    return [];
  }
}

/**
 * Get code event updates with flexible filtering
 * Used by extension agents or future UI panels
 *
 * @param {string} repo_id - Repository ID to fetch updates for
 * @param {Object} opts - Optional filters
 * @param {string} opts.since - ISO timestamp to fetch events after
 * @param {number} opts.limit - Max number of events to return
 * @param {Array<string>} opts.focus_systems - Filter by system names
 * @param {Array<string>} opts.focus_files - Filter by file paths
 * @param {Array<string>} opts.focus_impacts - Filter by impact types
 * @returns {Promise<Array>} Array of code event update objects
 */
export async function getCodeEventUpdates(repo_id, opts = {}) {
  if (!repo_id) {
    throw new Error("repo_id is required for getCodeEventUpdates");
  }

  const params = new URLSearchParams();
  params.set("repo_id", repo_id);

  if (opts.since) params.set("since", opts.since);
  if (opts.limit) params.set("limit", opts.limit.toString());

  // Use comma-separated encoding for array filters
  if (opts.focus_systems && opts.focus_systems.length > 0) {
    params.set("focus_systems", opts.focus_systems.join(","));
  }
  if (opts.focus_files && opts.focus_files.length > 0) {
    params.set("focus_files", opts.focus_files.join(","));
  }
  if (opts.focus_impacts && opts.focus_impacts.length > 0) {
    params.set("focus_impacts", opts.focus_impacts.join(","));
  }

  const url = `${API_BASE_URL}/api/v1/code-events/updates?${params.toString()}`;

  try {
    const res = await fetch(url, {
      method: "GET",
      credentials: "include",
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      const err = new Error(`Failed to fetch code event updates (${res.status})`);
      err.diagnostics = { status: res.status, body: text };
      throw err;
    }

    const data = await res.json();
    const events = data?.events ?? [];
    return Array.isArray(events) ? events : [];
  } catch (err) {
    console.error("[CodeEvents] Failed to fetch code event updates:", err);
    return [];
  }
}

/**
 * Fetch the stored cursor for code events (last seen marker)
 * Returns null on failure to avoid blocking UI flows.
 */
export async function getCodeEventCursor(repo_id, cursor_name = "code_events") {
  if (!repo_id) {
    console.warn("[CodeEvents] repo_id is required for getCodeEventCursor");
    return null;
  }

  const params = new URLSearchParams();
  params.set("repo_id", repo_id);
  if (cursor_name) params.set("cursor_name", cursor_name);

  const url = `${API_BASE_URL}/api/v1/code-events/cursor?${params.toString()}`;

  try {
    const res = await fetch(url, { method: "GET", credentials: "include" });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      console.error(
        `[CodeEvents] Failed to fetch cursor (${res.status})`,
        text
      );
      return null;
    }
    const data = await res.json().catch(() => null);
    return data;
  } catch (err) {
    console.error("[CodeEvents] Error fetching cursor:", err);
    return null;
  }
}

/**
 * Persist a cursor marker for code events.
 * Accepts either last_seen_event_id or last_seen_at.
 */
export async function setCodeEventCursor({
  repo_id,
  cursor_name = "code_events",
  last_seen_at,
  last_seen_event_id,
} = {}) {
  if (!repo_id) {
    console.warn("[CodeEvents] repo_id is required for setCodeEventCursor");
    return null;
  }

  const url = `${API_BASE_URL}/api/v1/code-events/cursor`;
  const payload = {
    repo_id,
    cursor_name,
  };

  if (last_seen_event_id) payload.last_seen_event_id = last_seen_event_id;
  if (last_seen_at) payload.last_seen_at = last_seen_at;

  try {
    const res = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      console.error(
        `[CodeEvents] Failed to set cursor (${res.status})`,
        text
      );
      return null;
    }

    const data = await res.json().catch(() => null);
    return data;
  } catch (err) {
    console.error("[CodeEvents] Error setting cursor:", err);
    return null;
  }
}

/**
 * Get code event updates since the stored cursor.
 * Returns { events, cursor } with safe defaults.
 */
export async function getUpdatesSinceCursor(
  repo_id,
  opts = {}
) {
  if (!repo_id) {
    console.warn("[CodeEvents] repo_id is required for getUpdatesSinceCursor");
    return { events: [], cursor: null };
  }

  const params = new URLSearchParams();
  params.set("repo_id", repo_id);

  const cursor_name = opts.cursor_name || "code_events";
  if (cursor_name) params.set("cursor_name", cursor_name);
  if (opts.limit) params.set("limit", String(opts.limit));

  if (Array.isArray(opts.focus_systems) && opts.focus_systems.length > 0) {
    params.set("focus_systems", opts.focus_systems.join(","));
  }
  if (Array.isArray(opts.focus_files) && opts.focus_files.length > 0) {
    params.set("focus_files", opts.focus_files.join(","));
  }
  if (Array.isArray(opts.focus_impacts) && opts.focus_impacts.length > 0) {
    params.set("focus_impacts", opts.focus_impacts.join(","));
  }

  const url = `${API_BASE_URL}/api/v1/code-events/updates-since-cursor?${params.toString()}`;

  try {
    const res = await fetch(url, { method: "GET", credentials: "include" });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      console.error(
        `[CodeEvents] Failed to fetch updates since cursor (${res.status})`,
        text
      );
      return { events: [], cursor: null };
    }

    const data = await res.json().catch(() => ({}));
    const events = Array.isArray(data?.events)
      ? data.events
      : Array.isArray(data?.items)
      ? data.items
      : [];
    return { events, cursor: data?.cursor || null };
  } catch (err) {
    console.error("[CodeEvents] Error fetching updates since cursor:", err);
    return { events: [], cursor: null };
  }
}
