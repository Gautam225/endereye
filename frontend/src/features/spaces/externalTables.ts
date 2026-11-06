import { compactCount } from "../../lib/format";
import type { ExternalTable, RefreshResult, TableChange } from "./types";

/** The most tables one space can use from a database. */
export const MAX_EXTERNAL_TABLES = 50;

export function refOf(table: Pick<ExternalTable, "schema" | "name">): string {
  return `${table.schema}.${table.name}`;
}

/** Tables whose name, schema or comment contains every word typed. */
export function filterTables(tables: ExternalTable[], query: string): ExternalTable[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return tables;
  return tables.filter((table) => {
    const text = `${refOf(table)} ${table.comment} ${table.kind}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
}

/** How many more tables can be picked, given those already in the space and those ticked. */
export function roomLeft(attached: number, picked: number): number {
  return Math.max(0, MAX_EXTERNAL_TABLES - attached - picked);
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** One line about what changed in a table. */
export function describeChange(change: TableChange): string {
  if (change.status === "missing") {
    return "No longer found, or no longer readable by the login. It stays in the space.";
  }
  const parts: string[] = [];
  if (change.added_columns.length > 0) {
    parts.push(
      `${plural(change.added_columns.length, "new column")} (${change.added_columns.join(", ")})`,
    );
  }
  if (change.removed_columns.length > 0) {
    parts.push(`${change.removed_columns.length} removed (${change.removed_columns.join(", ")})`);
  }
  if (change.type_changes.length > 0) {
    parts.push(
      change.type_changes.map((t) => `${t.column}: ${t.from_type} to ${t.to_type}`).join("; "),
    );
  }
  return parts.join(" · ") || "No changes.";
}

/** True when applying the refresh would change something. */
export function hasChanges(result: RefreshResult): boolean {
  return (
    result.tables.some((table) => table.status !== "unchanged") ||
    result.joins_added > 0 ||
    result.joins_removed > 0
  );
}

/** The tables grouped by schema, schemas in alphabetical order, tables in the order given. */
export function groupBySchema(
  tables: ExternalTable[],
): Array<{ schema: string; tables: ExternalTable[] }> {
  const groups = new Map<string, ExternalTable[]>();
  for (const table of tables)
    groups.set(table.schema, [...(groups.get(table.schema) ?? []), table]);
  return [...groups]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([schema, members]) => ({ schema, tables: members }));
}

/**
 * Which of the tables shown "Select all" would tick: those not in the space yet and not ticked
 * already, as many as the limit leaves room for.
 */
export function selectableRefs(
  shown: ExternalTable[],
  picked: ReadonlySet<string>,
  attached: number,
): string[] {
  const room = roomLeft(attached, picked.size);
  return shown
    .filter((table) => !table.attached_here && !picked.has(refOf(table)))
    .slice(0, room)
    .map(refOf);
}

/** A database's size estimate in a few characters: "~331.6K rows", or that it is not known. */
export function sizeText(estimatedRows: number | null): string {
  if (estimatedRows === null) return "size not known";
  return `~${compactCount(estimatedRows)} ${estimatedRows === 1 ? "row" : "rows"}`;
}
