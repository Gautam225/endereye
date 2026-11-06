import type { ColumnMeta, Relationship } from "./types";

export const RELATIONSHIPS: Array<{ value: Relationship; label: string }> = [
  { value: "many_to_one", label: "Many to one" },
  { value: "one_to_many", label: "One to many" },
  { value: "one_to_one", label: "One to one" },
];

/** "state, Zone ,state" becomes ["state", "Zone"]: trimmed, no blanks, no repeats (any case). */
export function parseSynonyms(text: string): string[] {
  const seen = new Map<string, string>();
  for (const part of text.split(",")) {
    const word = part.trim().replace(/\s+/g, " ");
    if (word && !seen.has(word.toLowerCase())) seen.set(word.toLowerCase(), word);
  }
  return [...seen.values()];
}

export interface ColumnEdit {
  description: string;
  synonyms: string;
}

export function editOf(column: ColumnMeta): ColumnEdit {
  return { description: column.description, synonyms: column.synonyms.join(", ") };
}

/** What changed between a column as saved and its edit; empty when nothing did. */
export function columnChange(
  column: ColumnMeta,
  edit: ColumnEdit | undefined,
): { description?: string; synonyms?: string[] } {
  if (!edit) return {};
  const change: { description?: string; synonyms?: string[] } = {};
  if (edit.description.trim() !== column.description) change.description = edit.description.trim();
  const synonyms = parseSynonyms(edit.synonyms);
  if (synonyms.join("\u0000") !== column.synonyms.join("\u0000")) change.synonyms = synonyms;
  return change;
}
