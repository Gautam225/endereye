const LAST_SPACE_KEY = "eoe.chat.space";
const LAST_CHAT_KEY = "eoe.chat.last";

export function rememberSpace(spaceId: string) {
  try {
    localStorage.setItem(LAST_SPACE_KEY, spaceId);
  } catch {
    // Storage may be blocked; the chat still works.
  }
}

export function lastSpace(): string | null {
  try {
    return localStorage.getItem(LAST_SPACE_KEY);
  } catch {
    return null;
  }
}

/** The chat a person was last in: which space, and which conversation (none for a new chat). */
export interface LastChat {
  spaceId: string;
  conversationId: string | null;
}

const chatKey = (userId: string) => `${LAST_CHAT_KEY}.${userId}`;

/** Remembered per person, so two people sharing a browser do not open each other's chats. */
export function rememberChat(userId: string, spaceId: string, conversationId: string | null) {
  try {
    const value: LastChat = { spaceId, conversationId };
    localStorage.setItem(chatKey(userId), JSON.stringify(value));
  } catch {
    // Storage may be blocked; "Ask" then opens the general chat, as it always did.
  }
}

export function lastChat(userId: string): LastChat | null {
  try {
    const raw = localStorage.getItem(chatKey(userId));
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return null;
    const { spaceId, conversationId } = value as Record<string, unknown>;
    if (typeof spaceId !== "string" || spaceId === "") return null;
    if (conversationId !== null && typeof conversationId !== "string") return null;
    return { spaceId, conversationId: conversationId || null };
  } catch {
    return null;
  }
}

/** Forget it, for a chat or space that no longer exists. */
export function forgetChat(userId: string) {
  try {
    localStorage.removeItem(chatKey(userId));
  } catch {
    // Nothing to do.
  }
}
