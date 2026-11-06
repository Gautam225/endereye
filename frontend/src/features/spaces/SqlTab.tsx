import { Play, TableProperties } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { asApiError } from "../../lib/api";
import { count, milliseconds, plural } from "../../lib/format";
import { useRunQuery, useTables } from "./queries";
import { ResultTable } from "./ResultTable";
import type { Space } from "./types";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/**
 * The draft survives switching tabs and reloading, per space, in this browser tab only.
 * null means "not typed yet", so the editor can start with an example query.
 */
function useDraft(spaceId: string): [string | null, (sql: string) => void] {
  const key = `eoe.sql.${spaceId}`;
  const [sql, setSql] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null;
    }
  });
  useEffect(() => {
    if (sql === null) return;
    try {
      sessionStorage.setItem(key, sql);
    } catch {
      // Storage may be blocked; the draft just won't be remembered.
    }
  }, [key, sql]);
  return [sql, setSql];
}

export function SqlTab({ space }: { space: Space }) {
  const tables = useTables(space.id);
  const run = useRunQuery(space.id);
  const [draft, setSql] = useDraft(space.id);
  const editor = useRef<HTMLTextAreaElement>(null);
  const error = run.error ? asApiError(run.error) : null;
  const first = tables.data?.[0];
  const sql = draft ?? (first ? `SELECT *\nFROM ${first.name}\nLIMIT 100` : "");

  function execute() {
    if (sql.trim() && !run.isPending) run.mutate(sql);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      execute();
    }
  }

  /** Put a table or column name where the cursor is. */
  function insert(text: string) {
    const box = editor.current;
    if (!box) return;
    const { selectionStart: start, selectionEnd: end } = box;
    setSql(sql.slice(0, start) + text + sql.slice(end));
    requestAnimationFrame(() => {
      box.focus();
      box.setSelectionRange(start + text.length, start + text.length);
    });
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_14rem]">
      <div className="min-w-0 space-y-5">
        <Card>
          <div className="p-3">
            <label htmlFor="sql-editor" className="sr-only">
              SQL query
            </label>
            <textarea
              id="sql-editor"
              ref={editor}
              value={sql}
              onChange={(event) => setSql(event.target.value)}
              onKeyDown={onKeyDown}
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
              rows={8}
              placeholder="SELECT region, sum(amount) AS total FROM sales GROUP BY region"
              className="block min-h-40 w-full resize-y rounded-md border border-border bg-bg p-3 font-mono text-[13px] leading-relaxed text-fg placeholder:text-subtle hover:border-border-strong focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
            <p className="text-[12.5px] text-subtle">
              One read-only SELECT over this space's tables.{" "}
              <kbd className="font-mono">{isMac ? "⌘" : "Ctrl"}+Enter</kbd> runs it.
            </p>
            <Button
              variant="primary"
              size="sm"
              loading={run.isPending}
              disabled={!sql.trim()}
              onClick={execute}
            >
              {!run.isPending && <Play aria-hidden />}
              Run
            </Button>
          </div>
        </Card>

        {error && (
          <Notice
            tone="error"
            title={error.code === "sql_not_allowed" ? "Query not allowed" : "Query failed"}
          >
            {error.message}
          </Notice>
        )}

        {run.data && !error && (
          <section aria-label="Result" className="space-y-2">
            <p role="status" className="text-[13px] text-muted">
              {plural(run.data.row_count, "row")} in {milliseconds(run.data.elapsed_ms)}
              {run.data.truncated &&
                ` · showing the first ${count(run.data.row_count)}; add LIMIT or filters to see the rest`}
            </p>
            <ResultTable columns={run.data.columns} rows={run.data.rows} className="bg-surface" />
          </section>
        )}
      </div>

      <Card className="h-fit">
        <CardHeader title="Tables" className="px-4 py-3" />
        {tables.isPending ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-5" />
            <Skeleton className="h-5" />
          </div>
        ) : tables.isError ? (
          <p className="p-4 text-[13px] text-danger">{tables.error.message}</p>
        ) : tables.data.length === 0 ? (
          <p className="p-4 text-[13px] text-muted">No tables yet. Add data on the Data tab.</p>
        ) : (
          <ul className="max-h-[32rem] space-y-3 overflow-auto p-3">
            {tables.data.map((table) => (
              <li key={table.id}>
                <button
                  type="button"
                  onClick={() => insert(table.name)}
                  title="Insert the table name"
                  className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left font-mono text-[12.5px] font-medium hover:bg-surface-2"
                >
                  <TableProperties aria-hidden className="size-3.5 shrink-0 text-subtle" />
                  <span className="truncate">{table.name}</span>
                </button>
                <ul className="mt-0.5 ml-[1.1rem] border-l border-border pl-2">
                  {table.columns.map((column) => (
                    <li key={column.name}>
                      <button
                        type="button"
                        onClick={() => insert(column.name)}
                        title={`Insert ${column.name} (${column.type.toLowerCase()})`}
                        className="flex w-full items-baseline justify-between gap-2 rounded px-1 py-px text-left font-mono text-[12px] text-muted hover:bg-surface-2 hover:text-fg"
                      >
                        <span className="truncate">{column.name}</span>
                        <span className="shrink-0 text-[10.5px] text-subtle">
                          {column.type.toLowerCase()}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
