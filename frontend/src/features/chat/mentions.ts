import type { Mention } from "./types";

/** A document or a table a question can point at with @name. */
export interface Mentionable {
  id: string;
  /** What to type after the @: the file or table name without spaces. */
  mention: string;
  filename: string;
  /** Added in this chat, part of the space, or a table of the space's data. */
  scope: "chat" | "space" | "table";
}

export const MAX_MENTIONS = 10;
const SHOWN = 50; // the list scrolls, so every table and document of a space can be reached

/** The `@word` being typed right before the cursor, or null when the cursor is not in one. */
export function activeMention(
  text: string,
  caret: number,
): { start: number; query: string } | null {
  const before = text.slice(0, caret);
  const match = /(^|\s)@([A-Za-z0-9_-]*)$/.exec(before);
  if (!match) return null;
  const query = match[2] ?? "";
  return { start: before.length - query.length - 1, query };
}

/** What to offer for what has been typed after the @: names that start with it first. */
// (A table is offered under its name with spaces and symbols as underscores, as the server does.)
export function tableMention(name: string): string {
  return name.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "") || "table";
}

export function filterMentionables(documents: Mentionable[], query: string): Mentionable[] {
  const needle = query.toLowerCase();
  const starts = documents.filter((d) => d.mention.toLowerCase().startsWith(needle));
  const contains = documents.filter(
    (d) => !starts.includes(d) && d.mention.toLowerCase().includes(needle),
  );
  return [...starts, ...contains].slice(0, SHOWN);
}

/** Replace the `@query` before the cursor with the full mention and a space. */
export function insertMention(
  text: string,
  caret: number,
  active: { start: number },
  mention: string,
): { text: string; caret: number } {
  const inserted = `@${mention} `;
  return {
    text: text.slice(0, active.start) + inserted + text.slice(caret).replace(/^ /, ""),
    caret: active.start + inserted.length,
  };
}

/** The documents a finished question points at: every `@name` that matches one, once each. */
export function parseMentions(text: string, documents: Mentionable[]): Mention[] {
  const byName = new Map(documents.map((d) => [d.mention.toLowerCase(), d]));
  const found = new Map<string, Mention>();
  for (const match of text.matchAll(/(?:^|\s)@([A-Za-z0-9_-]+)/g)) {
    const document = byName.get((match[1] ?? "").toLowerCase());
    if (document && !found.has(document.id)) {
      found.set(document.id, { id: document.id, name: document.mention });
    }
  }
  return [...found.values()].slice(0, MAX_MENTIONS);
}

/** A question split into plain text and the `@name` parts that point at documents. */
export function splitMentions(
  text: string,
  names: string[],
): Array<{ text: string; mention: boolean }> {
  if (names.length === 0) return [{ text, mention: false }];
  const lower = new Set(names.map((n) => n.toLowerCase()));
  return text
    .split(/(\s@[A-Za-z0-9_-]+|^@[A-Za-z0-9_-]+)/)
    .filter((part) => part !== "")
    .map((part) => ({ text: part, mention: lower.has(part.trim().slice(1).toLowerCase()) }));
}
