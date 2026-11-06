import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "../../lib/cn";
import { compareValues, formatCell, formatValue, isNumericType } from "./cells";
import type { Column } from "./types";

type Sort = { column: number; direction: "asc" | "desc" } | null;

/**
 * Rows from a query or preview. Numbers and dates are formatted for reading (the exact value is
 * in the tooltip), a click on a heading sorts by it, the box scrolls on its own and the heading
 * stays visible.
 */
export function ResultTable({
  columns,
  rows,
  className,
  plain = false,
}: {
  columns: Column[];
  rows: unknown[][];
  className?: string;
  /** Hide the type under each heading and write a missing value as a dash (for chart data). */
  plain?: boolean;
}) {
  const [sort, setSort] = useState<Sort>(null);
  const numeric = columns.map((column) => isNumericType(column.type));

  const shown = useMemo(() => {
    if (!sort) return rows;
    const type = columns[sort.column]?.type ?? "";
    const factor = sort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = a[sort.column];
      const y = b[sort.column];
      const empty = x == null || y == null;
      // Empty values stay last whichever way the column is sorted.
      return empty ? compareValues(x, y, type) : factor * compareValues(x, y, type);
    });
  }, [rows, columns, sort]);

  function toggle(index: number) {
    setSort((current) =>
      current?.column !== index
        ? { column: index, direction: "asc" }
        : current.direction === "asc"
          ? { column: index, direction: "desc" }
          : null,
    );
  }

  return (
    <div
      className={cn("max-h-[26rem] overflow-auto rounded-lg border border-border", className)}
      tabIndex={0}
      role="region"
      aria-label="Result rows"
    >
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-10 bg-surface-2">
          <tr>
            {columns.map((column, index) => {
              const sorted = sort?.column === index ? sort.direction : null;
              return (
                <th
                  key={`${column.name}-${index}`}
                  scope="col"
                  aria-sort={
                    sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
                  }
                  className="border-b border-border p-0 align-bottom font-medium whitespace-nowrap"
                >
                  <button
                    type="button"
                    onClick={() => toggle(index)}
                    title={`Sort by ${column.name}`}
                    className={cn(
                      "group flex w-full items-end gap-1.5 px-3 py-2.5 transition-colors hover:bg-border/40",
                      numeric[index] ? "flex-row-reverse text-right" : "text-left",
                    )}
                  >
                    <span className="min-w-0">
                      <span className="block text-fg">{column.name}</span>
                      {!plain && (
                        <span className="block font-mono text-[11px] font-normal text-subtle">
                          {column.type.toLowerCase()}
                        </span>
                      )}
                    </span>
                    {sorted === "asc" ? (
                      <ArrowUp aria-hidden className="mb-0.5 size-3.5 shrink-0 text-accent" />
                    ) : sorted === "desc" ? (
                      <ArrowDown aria-hidden className="mb-0.5 size-3.5 shrink-0 text-accent" />
                    ) : (
                      <ChevronsUpDown
                        aria-hidden
                        className="mb-0.5 size-3.5 shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100"
                      />
                    )}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="text-[13px]">
          {shown.map((row, rowIndex) => (
            <tr key={rowIndex} className="even:bg-surface-2/30 hover:bg-surface-2/70">
              {row.map((value, index) => {
                const { text, isNull } = formatValue(value, columns[index]?.type ?? "");
                const exact = formatCell(value).text;
                return (
                  <td
                    key={index}
                    title={exact !== text || text.length > 60 ? exact : undefined}
                    className={cn(
                      "max-w-[22rem] truncate border-b border-border/60 px-3 py-2 whitespace-nowrap",
                      numeric[index] && "text-right tabular-nums",
                      isNull && "text-subtle italic",
                    )}
                  >
                    {plain && isNull ? "—" : text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="px-3 py-6 text-center text-muted">No rows.</p>}
    </div>
  );
}
