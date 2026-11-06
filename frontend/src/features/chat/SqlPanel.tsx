import { Bookmark, Check, ChevronDown, Copy, Pencil, Play } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import { Button } from "../../components/ui/Button";
import { BareTextArea, TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { asApiError } from "../../lib/api";
import { milliseconds, plural } from "../../lib/format";
import { useCreateKnowledge, useRunQuery } from "../spaces/queries";
import { ResultTable } from "../spaces/ResultTable";
import { VerifiedBadge } from "./VerifiedBadge";

/**
 * The query behind an answer: view and copy it; editors can also change it, run it, and save a
 * verified question with its SQL as an example (so the next similar question works better).
 */
export function SqlPanel({
  spaceId,
  sql,
  question,
  editor,
  attempts,
  elapsedMs,
  trusted,
}: {
  spaceId: string;
  sql: string;
  question: string;
  editor: boolean;
  attempts: number;
  elapsedMs?: number;
  trusted: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(sql);
  const [copied, setCopied] = useState(false);
  const run = useRunQuery(spaceId);
  const runError = run.error ? asApiError(run.error).message : null;
  const current = editing ? draft : sql;

  async function copy() {
    try {
      await navigator.clipboard.writeText(current);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be blocked; the text is still selectable.
    }
  }

  function execute() {
    if (draft.trim() && !run.isPending) run.mutate(draft);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      execute();
    }
  }

  return (
    <details className="group rounded-lg border border-border">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[13px] font-medium">
        <ChevronDown
          aria-hidden
          className="size-4 text-subtle transition-transform group-open:rotate-180"
        />
        SQL
        {trusted && <VerifiedBadge />}
        <span className="ml-auto font-normal text-subtle">
          {attempts > 1 ? `${attempts} tries · ` : ""}
          {elapsedMs !== undefined && milliseconds(elapsedMs)}
        </span>
      </summary>
      <div className="space-y-3 border-t border-border p-3">
        {editing ? (
          <BareTextArea
            aria-label="SQL"
            rows={Math.min(Math.max(draft.split("\n").length + 1, 4), 16)}
            spellCheck={false}
            className="font-mono text-[13px]"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onKeyDown}
          />
        ) : (
          <pre className="max-h-72 overflow-auto rounded-md bg-surface-2/60 px-3 py-2 font-mono text-[12.5px] whitespace-pre-wrap">
            {sql}
          </pre>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={copy}>
            {copied ? (
              <Check aria-hidden className="size-3.5" />
            ) : (
              <Copy aria-hidden className="size-3.5" />
            )}
            {copied ? "Copied" : "Copy"}
          </Button>
          {editor && !editing && (
            <Button
              size="sm"
              onClick={() => {
                setDraft(sql);
                setEditing(true);
              }}
            >
              <Pencil aria-hidden className="size-3.5" />
              Edit
            </Button>
          )}
          {editor && editing && (
            <>
              <Button size="sm" variant="primary" loading={run.isPending} onClick={execute}>
                <Play aria-hidden className="size-3.5" />
                Run
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setEditing(false);
                  run.reset();
                }}
              >
                Discard changes
              </Button>
            </>
          )}
        </div>
        {runError && (
          <Notice tone="error" title="The query did not run">
            {runError}
          </Notice>
        )}
        {run.data && (
          <div className="space-y-2">
            <p className="text-[12.5px] text-muted">
              Your edited query returned {plural(run.data.row_count, "row")} in{" "}
              {milliseconds(run.data.elapsed_ms)}.
            </p>
            <ResultTable columns={run.data.columns} rows={run.data.rows} />
          </div>
        )}
        {editor && editing && <SaveExample spaceId={spaceId} question={question} sql={current} />}
      </div>
    </details>
  );
}

/** Saves a question with its SQL as an example, so similar questions are answered the same way. */
export function SaveExample({
  spaceId,
  question,
  sql,
  initiallyTrusted = false,
  label = "Save as an example",
}: {
  spaceId: string;
  question: string;
  sql: string;
  /** Offered from a good answer: the box to mark it Trusted starts ticked. */
  initiallyTrusted?: boolean;
  label?: string;
}) {
  const create = useCreateKnowledge(spaceId);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(question);
  const [trusted, setTrusted] = useState(initiallyTrusted);
  const error = create.error ? asApiError(create.error).message : null;

  if (create.isSuccess) {
    return (
      <p role="status" className="flex items-center gap-2 text-[13px] text-muted">
        <Check aria-hidden className="size-4 text-success" />
        Saved as an example{trusted ? " and marked Trusted" : ""}.
      </p>
    );
  }
  if (!open) {
    return (
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        <Bookmark aria-hidden className="size-3.5" />
        {label}
      </Button>
    );
  }
  return (
    <div className="space-y-3 rounded-md border border-border bg-surface-2/40 p-3">
      <p className="text-[13px] text-muted">
        Save this question with the SQL above, so similar questions are answered the same way. Only
        mark it Trusted after you have checked the result.
      </p>
      {error && (
        <Notice tone="error" title="Not saved">
          {error}
        </Notice>
      )}
      <TextField
        label="Question, as a person would ask it"
        maxLength={500}
        value={title}
        onChange={(event) => setTitle(event.target.value)}
      />
      <label className="flex items-center gap-2 text-[13px] text-muted">
        <input
          type="checkbox"
          checked={trusted}
          onChange={(event) => setTrusted(event.target.checked)}
          className="size-3.5 accent-[var(--color-accent)]"
        />
        I have verified this SQL (Trusted)
      </label>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <Button
          size="sm"
          variant="primary"
          loading={create.isPending}
          disabled={!title.trim()}
          onClick={() =>
            create.mutate({ kind: "example_sql", title: title.trim(), body: sql, trusted })
          }
        >
          Save example
        </Button>
      </div>
    </div>
  );
}
