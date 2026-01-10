import { API_BASE_URL } from "../config";

export async function searchRAG(roomId, query, limit = 10) {
  const payload = {
    query,
    limit,
  };
  if (roomId) payload.room_id = roomId;

  const response = await fetch(`${API_BASE_URL}/api/rag/search`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const message = detail?.detail || detail?.message || "RAG search failed";
    throw new Error(`${message} (${response.status})`);
  }

  return response.json();
}

export function formatRAGContext(results) {
  if (!Array.isArray(results) || results.length === 0) return "";

  const lines = results.map((item, index) => {
    const speaker =
      item.user_name || item.actor_name || item.sender_name || "Unknown";
    const timestamp = item.timestamp || item.created_at || item.at || "";
    const location = item.room_name || item.room_id || item.chat_name || "";
    const rawContent = item.content || item.text || item.message || "";
    const cleaned = String(rawContent).replace(/\s+/g, " ").trim();
    const snippet = cleaned.length > 300 ? `${cleaned.slice(0, 297)}...` : cleaned;

    const meta = [location, timestamp].filter(Boolean).join(" ");
    const prefix = meta ? `(${index + 1}) [${meta}]` : `(${index + 1})`;
    return `${prefix} ${speaker}: ${snippet}`;
  });

  return `<retrieved_context>\n${lines.join("\n")}\n</retrieved_context>`;
}
