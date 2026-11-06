import { BookOpen, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { BareTextArea, TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import {
  useCreateKnowledge,
  useDeleteKnowledge,
  useKnowledge,
  useUpdateKnowledge,
} from "./queries";
import { ExpressionsCard } from "./ExpressionsCard";
import type { KnowledgeItem, KnowledgeKind, Space } from "./types";

const KINDS: Array<{ value: KnowledgeKind; label: string }> = [
  { value: "instruction", label: "Instruction" },
  { value: "glossary", label: "Glossary term" },
  { value: "example_sql", label: "Example SQL" },
  { value: "clarification", label: "When to ask" },
];

/** Labels and examples for the fields of each kind of item. */
const FIELDS: Record<
  KnowledgeKind,
  { title: string | null; titleHint: string; body: string; bodyHint: string }
> = {
  instruction: {
    title: null,
    titleHint: "",
    body: "Instruction",
    bodyHint: "The fiscal year starts on 1 April.",
  },
  glossary: {
    title: "Term",
    titleHint: "Active customer",
    body: "Meaning",
    bodyHint: "A customer with at least one completed order in the last 90 days.",
  },
  example_sql: {
    title: "Question, as a person would ask it",
    titleHint: "What is the total revenue by region?",
    body: "SQL",
    bodyHint: "SELECT region, sum(amount) FROM sales GROUP BY 1",
  },
  clarification: {
    title: "When should it ask?",
    titleHint: "the user asks about sales without a time period",
    body: "What should it ask?",
    bodyHint: "Which period do you mean: this month, this quarter or this year?",
  },
};

const KIND_LABEL: Record<KnowledgeKind, string> = {
  instruction: "Instruction",
  glossary: "Glossary",
  example_sql: "Example SQL",
  clarification: "When to ask",
};

/** What the AI is told besides the data: rules, terms and example questions. */
export function KnowledgeTab({ space }: { space: Space }) {
  const editor = space.my_role === "editor";
  return (
    <div className="space-y-5">
      <ItemsCard spaceId={space.id} editor={editor} />
      <ExpressionsCard spaceId={space.id} editor={editor} />
    </div>
  );
}

// ── Instructions, glossary, example SQL ──────────────────────────────────────

function ItemsCard({ spaceId, editor }: { spaceId: string; editor: boolean }) {
  const items = useKnowledge(spaceId);
  return (
    <Card>
      <CardHeader
        title="Instructions, glossary and examples"
        description="Short rules, business terms, and example questions with the SQL that answers them. Example SQL is checked against this space's tables."
      />
      {editor && <AddItem spaceId={spaceId} />}
      {items.isPending ? (
        <Skeleton className="m-5 h-12" />
      ) : items.isError ? (
        <Notice tone="error" title="Could not load the knowledge" className="m-5">
          {items.error.message}
        </Notice>
      ) : items.data.length === 0 ? (
        <EmptyState icon={BookOpen} title="Nothing here yet">
          {editor
            ? "Add the rules and terms people in this space use, and the questions they ask most."
            : "Editors have not added any instructions, terms or examples."}
        </EmptyState>
      ) : (
        <ul className="divide-y divide-border">
          {items.data.map((item) => (
            <ItemRow key={item.id} spaceId={spaceId} item={item} editor={editor} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function AddItem({ spaceId }: { spaceId: string }) {
  const create = useCreateKnowledge(spaceId);
  const [kind, setKind] = useState<KnowledgeKind>("instruction");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [note, setNote] = useState("");
  const [trusted, setTrusted] = useState(false);
  const error = create.error ? asApiError(create.error) : null;
  const needsTitle = kind !== "instruction";
  const ready = body.trim() !== "" && (!needsTitle || title.trim() !== "");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    create.mutate(
      {
        kind,
        title: title.trim(),
        body: body.trim(),
        ...(kind === "example_sql" ? { trusted, note: note.trim() } : {}),
      },
      {
        onSuccess: () => {
          setTitle("");
          setBody("");
          setNote("");
          setTrusted(false);
        },
      },
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-3 border-b border-border p-5">
      <SegmentedControl
        label="What to add"
        options={KINDS}
        value={kind}
        onChange={(value) => {
          setKind(value);
          create.reset();
        }}
      />
      {error && (
        <Notice tone="error" title="Not added">
          {error.fieldErrors.body ?? error.fieldErrors.title ?? error.message}
        </Notice>
      )}
      {needsTitle && (
        <TextField
          label={FIELDS[kind].title ?? ""}
          placeholder={FIELDS[kind].titleHint}
          maxLength={500}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      )}
      <div className="space-y-1.5">
        <label htmlFor="knowledge-body" className="block text-[13px] font-medium">
          {FIELDS[kind].body}
        </label>
        <BareTextArea
          id="knowledge-body"
          rows={kind === "example_sql" ? 4 : 3}
          maxLength={20_000}
          spellCheck={kind !== "example_sql"}
          className={cn(kind === "example_sql" && "font-mono text-[13px]")}
          placeholder={FIELDS[kind].bodyHint}
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />
      </div>
      {kind === "example_sql" && (
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <TextField
            label="When is it especially relevant? (optional)"
            maxLength={1000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <label className="flex h-9 items-center gap-2 text-[13px] text-muted">
            <input
              type="checkbox"
              checked={trusted}
              onChange={(event) => setTrusted(event.target.checked)}
              className="size-3.5 accent-[var(--color-accent)]"
            />
            I have verified this SQL (Trusted)
          </label>
        </div>
      )}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={create.isPending} disabled={!ready}>
          Add {KIND_LABEL[kind].toLowerCase()}
        </Button>
      </div>
    </form>
  );
}

function ItemRow({
  spaceId,
  item,
  editor,
}: {
  spaceId: string;
  item: KnowledgeItem;
  editor: boolean;
}) {
  const remove = useDeleteKnowledge(spaceId);
  const update = useUpdateKnowledge(spaceId);
  const [confirming, setConfirming] = useState(false);
  const failure = remove.error ?? update.error;
  const sql = item.kind === "example_sql";

  return (
    <li className="space-y-1.5 px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={sql ? "accent" : "neutral"}>{KIND_LABEL[item.kind]}</Badge>
        {item.trusted && <Badge tone="ok">Trusted</Badge>}
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">
          {item.title || item.body}
        </span>
        {editor &&
          (confirming ? (
            <div className="flex shrink-0 gap-1">
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                Keep
              </Button>
              <Button
                size="sm"
                className="text-danger hover:bg-danger-soft"
                loading={remove.isPending}
                onClick={() => remove.mutate(item.id)}
              >
                Remove
              </Button>
            </div>
          ) : (
            <div className="flex shrink-0 items-center gap-1">
              {sql && (
                <Button
                  size="sm"
                  variant="ghost"
                  loading={update.isPending}
                  onClick={() => update.mutate({ id: item.id, change: { trusted: !item.trusted } })}
                >
                  {item.trusted ? "Remove trust" : "Mark trusted"}
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove ${item.title || "this item"}`}
                onClick={() => setConfirming(true)}
              >
                <Trash2 aria-hidden />
              </Button>
            </div>
          ))}
      </div>
      {(item.title || sql) && (
        <pre
          className={cn(
            "overflow-x-auto rounded-md bg-surface-2/60 px-3 py-2 text-[12.5px] whitespace-pre-wrap",
            sql && "font-mono",
          )}
        >
          {item.body}
        </pre>
      )}
      {item.note && <p className="text-[12.5px] text-subtle">{item.note}</p>}
      {failure && (
        <Notice tone="error" title="That didn't work">
          {asApiError(failure).message}
        </Notice>
      )}
    </li>
  );
}
