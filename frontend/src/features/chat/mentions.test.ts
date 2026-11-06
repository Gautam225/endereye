import { describe, expect, it } from "vitest";

import {
  activeMention,
  filterMentionables,
  insertMention,
  parseMentions,
  tableMention,
  splitMentions,
  type Mentionable,
} from "./mentions";

const docs: Mentionable[] = [
  { id: "1", mention: "sales_policy_2025", filename: "Sales policy 2025.pdf", scope: "space" },
  { id: "2", mention: "notes", filename: "notes.txt", scope: "chat" },
  { id: "3", mention: "policy-draft", filename: "policy-draft.md", scope: "chat" },
];

describe("activeMention", () => {
  it("finds the @word right before the cursor", () => {
    expect(activeMention("what does @sal", 14)).toEqual({ start: 10, query: "sal" });
    expect(activeMention("@", 1)).toEqual({ start: 0, query: "" });
    expect(activeMention("see @notes and more", 10)).toEqual({ start: 4, query: "notes" });
  });

  it("is null when the cursor is not inside a mention", () => {
    expect(activeMention("hello world", 11)).toBeNull();
    expect(activeMention("mail me@example", 15)).toBeNull(); // an email is not a mention
    expect(activeMention("see @notes and", 14)).toBeNull();
  });
});

describe("filterMentionables", () => {
  it("lists names that start with the typed text first, then names that contain it", () => {
    expect(filterMentionables(docs, "pol").map((d) => d.id)).toEqual(["3", "1"]);
    expect(filterMentionables(docs, "").map((d) => d.id)).toEqual(["1", "2", "3"]);
    expect(filterMentionables(docs, "zzz")).toEqual([]);
    expect(filterMentionables(docs, "NOTES").map((d) => d.id)).toEqual(["2"]);
  });
});

describe("insertMention", () => {
  it("replaces the typed part with the full name and puts the cursor after it", () => {
    const active = activeMention("what does @sal say", 14);
    expect(active).not.toBeNull();
    expect(insertMention("what does @sal say", 14, active!, "sales_policy_2025")).toEqual({
      text: "what does @sales_policy_2025 say",
      caret: 29,
    });
  });
});

describe("parseMentions", () => {
  it("returns each mentioned document once, ignoring unknown names and emails", () => {
    expect(
      parseMentions("Compare @notes with @Sales_Policy_2025 and @notes, me@notes.com @nope", docs),
    ).toEqual([
      { id: "2", name: "notes" },
      { id: "1", name: "sales_policy_2025" },
    ]);
    expect(parseMentions("no mentions", docs)).toEqual([]);
  });
});

describe("splitMentions", () => {
  it("marks the parts that point at documents", () => {
    expect(splitMentions("what is in @notes today", ["notes"])).toEqual([
      { text: "what is in", mention: false },
      { text: " @notes", mention: true },
      { text: " today", mention: false },
    ]);
    expect(splitMentions("@notes first", ["notes"])[0]).toEqual({ text: "@notes", mention: true });
    expect(splitMentions("plain text", [])).toEqual([{ text: "plain text", mention: false }]);
    expect(splitMentions("about @other", ["notes"]).every((p) => !p.mention)).toBe(true);
  });
});

describe("tables", () => {
  const withTable: Mentionable[] = [
    ...docs,
    { id: "9", mention: "staff_list", filename: "Table · 12 rows", scope: "table" },
  ];

  it("names a table the way the server does", () => {
    expect(tableMention("staff list")).toBe("staff_list");
    expect(tableMention("orders (2025)")).toBe("orders_2025");
    expect(tableMention("###")).toBe("table");
  });

  it("offers tables next to documents and reads them back from the question", () => {
    expect(filterMentionables(withTable, "staff").map((d) => d.id)).toEqual(["9"]);
    expect(parseMentions("who is in @staff_list per @notes?", withTable)).toEqual([
      { id: "9", name: "staff_list" },
      { id: "2", name: "notes" },
    ]);
  });
});
