import type { Conversation } from "./types";

const DAY = 86_400_000;

/** "Today", "Yesterday", "Previous 7 days", "Earlier" */
export function dayGroup(iso: string, now: number = Date.now()): string {
  const startOfToday = new Date(now).setHours(0, 0, 0, 0);
  const then = new Date(iso).getTime();
  if (then >= startOfToday) return "Today";
  if (then >= startOfToday - DAY) return "Yesterday";
  if (then >= startOfToday - 7 * DAY) return "Previous 7 days";
  return "Earlier";
}

const PINNED = "Pinned";
const ORDER = [PINNED, "Today", "Yesterday", "Previous 7 days", "Earlier"];

export function groupConversations(items: Conversation[], now?: number) {
  const groups = new Map<string, Conversation[]>();
  for (const item of items) {
    const key = item.pinned ? PINNED : dayGroup(item.updated_at, now);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return ORDER.filter((name) => groups.has(name)).map((name) => ({
    name,
    items: groups.get(name) ?? [],
  }));
}
