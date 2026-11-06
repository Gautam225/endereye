import { describe, expect, it } from "vitest";

import { dayGroup, groupConversations } from "./groups";

const NOW = new Date("2025-06-15T15:00:00").getTime();
const at = (iso: string) => new Date(iso).toISOString();
const item = (id: string, updated: string) => ({
  id,
  title: id,
  pinned: false,
  created_at: updated,
  updated_at: at(updated),
});

describe("dayGroup", () => {
  it("names the day a conversation was last used", () => {
    expect(dayGroup(at("2025-06-15T01:00:00"), NOW)).toBe("Today");
    expect(dayGroup(at("2025-06-14T23:00:00"), NOW)).toBe("Yesterday");
    expect(dayGroup(at("2025-06-10T10:00:00"), NOW)).toBe("Previous 7 days");
    expect(dayGroup(at("2025-05-01T10:00:00"), NOW)).toBe("Earlier");
  });
});

describe("groupConversations", () => {
  it("keeps the order of the groups and of the items inside them, and skips empty groups", () => {
    const groups = groupConversations(
      [
        item("a", "2025-06-15T10:00:00"),
        item("b", "2025-06-15T09:00:00"),
        item("c", "2025-04-01T09:00:00"),
      ],
      NOW,
    );

    expect(groups.map((g) => [g.name, g.items.map((i) => i.id)])).toEqual([
      ["Today", ["a", "b"]],
      ["Earlier", ["c"]],
    ]);
    expect(groupConversations([], NOW)).toEqual([]);
  });

  it("puts pinned chats first, whatever their age, in the order the server gave", () => {
    const groups = groupConversations(
      [
        { ...item("old", "2025-04-01T09:00:00"), pinned: true },
        item("a", "2025-06-15T10:00:00"),
        { ...item("older", "2025-03-01T09:00:00"), pinned: true },
      ],
      NOW,
    );

    expect(groups.map((g) => [g.name, g.items.map((i) => i.id)])).toEqual([
      ["Pinned", ["old", "older"]],
      ["Today", ["a"]],
    ]);
  });
});
