import { Calculator, ChevronDown, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { BareTextArea, SelectField, TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { parseSynonyms } from "./metadata";
import { MetricDetails } from "./MetricDetails";
import { useCreateExpression, useDeleteExpression, useExpressions, useTables } from "./queries";
import type { ExpressionType, SqlExpression } from "./types";

const TYPES: Array<{ value: ExpressionType; label: string }> = [
  { value: "measure", label: "Measure" },
  { value: "filter", label: "Filter" },
  { value: "dimension", label: "Dimension" },
];

const HINTS: Record<ExpressionType, { what: string; example: string }> = {
  measure: {
    what: "A number that adds up many rows, such as a KPI.",
    example: "sum(amount) FILTER (WHERE status <> 'cancelled')",
  },
  filter: {
    what: "A true / false condition, such as large orders.",
    example: "amount > 10000",
  },
  dimension: {
    what: "A value to group by, such as a size band or a fiscal quarter.",
    example: "date_trunc('month', order_date)",
  },
};

/**
 * Business definitions written as SQL. The AI uses them exactly as written, so "net revenue" always
 * means the same thing. Each one is tested on its table before it is saved.
 */
export function ExpressionsCard({ spaceId, editor }: { spaceId: string; editor: boolean }) {
  const expressions = useExpressions(spaceId);
  return (
    <Card>
      <CardHeader
        title="Business definitions"
        description="Measures, filters and groupings written as SQL. They are applied exactly as written, which is more reliable than describing a metric in words. Default filters are added to every question that uses their table."
      />
      {editor && <AddExpression spaceId={spaceId} />}
      {expressions.isPending ? (
        <Skeleton className="m-5 h-12" />
      ) : expressions.isError ? (
        <Notice tone="error" title="Could not load the definitions" className="m-5">
          {expressions.error.message}
        </Notice>
      ) : expressions.data.length === 0 ? (
        <EmptyState icon={Calculator} title="No definitions yet">
          {editor
            ? "Define the metrics people ask about most, such as net revenue or win rate."
            : "Editors have not defined any metrics or filters."}
        </EmptyState>
      ) : (
        <ul className="divide-y divide-border">
          {expressions.data.map((item) => (
            <Row key={item.id} spaceId={spaceId} item={item} editor={editor} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function AddExpression({ spaceId }: { spaceId: string }) {
  const tables = useTables(spaceId);
  const create = useCreateExpression(spaceId);
  const [type, setType] = useState<ExpressionType>("measure");
  const [name, setName] = useState("");
  const [table, setTable] = useState("");
  const [expression, setExpression] = useState("");
  const [description, setDescription] = useState("");
  const [synonyms, setSynonyms] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const error = create.error ? asApiError(create.error) : null;
  const ready = name.trim() !== "" && expression.trim() !== "";

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    create.mutate(
      {
        name: name.trim(),
        type,
        expression: expression.trim(),
        table_name: table || null,
        description: description.trim(),
        synonyms: parseSynonyms(synonyms),
        is_default: type === "filter" && isDefault,
      },
      {
        onSuccess: () => {
          setName("");
          setExpression("");
          setDescription("");
          setSynonyms("");
          setIsDefault(false);
        },
      },
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-3 border-b border-border p-5">
      <SegmentedControl
        label="Kind of definition"
        options={TYPES}
        value={type}
        onChange={(value) => {
          setType(value);
          setIsDefault(false);
          create.reset();
        }}
      />
      <p className="text-[12.5px] text-subtle">{HINTS[type].what}</p>
      {error && (
        <Notice tone="error" title="Not saved">
          {error.fieldErrors.name ?? error.fieldErrors.expression ?? error.message}
        </Notice>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label="Name"
          placeholder="Net revenue"
          maxLength={120}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <SelectField
          label="Table it is written for"
          value={table}
          options={[
            { value: "", label: "Not tied to one table" },
            ...(tables.data ?? []).map((t) => ({ value: t.name, label: t.name })),
          ]}
          onChange={(event) => setTable(event.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="expression-sql" className="block text-[13px] font-medium">
          SQL expression
        </label>
        <BareTextArea
          id="expression-sql"
          rows={2}
          spellCheck={false}
          maxLength={2000}
          className="font-mono text-[13px]"
          placeholder={HINTS[type].example}
          value={expression}
          onChange={(event) => setExpression(event.target.value)}
        />
        <p className="text-[12.5px] text-subtle">
          Only the expression, not a whole query. It is run on the table before it is saved.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label="What it means (optional)"
          maxLength={1000}
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <TextField
          label="Other names, separated by commas (optional)"
          placeholder="net sales, turnover"
          value={synonyms}
          onChange={(event) => setSynonyms(event.target.value)}
        />
      </div>
      {type === "filter" && (
        <label className="flex items-center gap-2 text-[13px] text-muted">
          <input
            type="checkbox"
            checked={isDefault}
            onChange={(event) => setIsDefault(event.target.checked)}
            className="size-3.5 accent-[var(--color-accent)]"
          />
          Apply by default to every question that uses this table
        </label>
      )}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={create.isPending} disabled={!ready}>
          Test and add {type}
        </Button>
      </div>
    </form>
  );
}

function Row({ spaceId, item, editor }: { spaceId: string; item: SqlExpression; editor: boolean }) {
  const remove = useDeleteExpression(spaceId);
  const [confirming, setConfirming] = useState(false);
  const [open, setOpen] = useState(false);

  return (
    <li className="space-y-1.5 px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent">{TYPES.find((t) => t.value === item.type)?.label}</Badge>
        {item.is_default && <Badge tone="ok">Default</Badge>}
        {item.tests_failing > 0 ? (
          <Badge tone="error">
            {item.tests_failing} of {item.tests_total} tests fail
          </Badge>
        ) : (
          item.tests_total > 0 && <Badge tone="ok">{item.tests_total} tests pass</Badge>
        )}
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{item.name}</span>
        {item.table_name && (
          <span className="font-mono text-[12px] text-subtle">{item.table_name}</span>
        )}
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
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${item.name}`}
              onClick={() => setConfirming(true)}
            >
              <Trash2 aria-hidden />
            </Button>
          ))}
      </div>
      <pre className="overflow-x-auto rounded-md bg-surface-2/60 px-3 py-2 font-mono text-[12.5px] whitespace-pre-wrap">
        {item.expression}
      </pre>
      {(item.description || item.synonyms.length > 0) && (
        <p className="text-[12.5px] text-subtle">
          {item.description}
          {item.synonyms.length > 0 && ` Also called: ${item.synonyms.join(", ")}.`}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-3 text-[12.5px] text-subtle">
        <span>
          Owner: {item.owner_name ?? "nobody"} · version {item.version}
        </span>
        <Button
          size="sm"
          variant="ghost"
          aria-expanded={open}
          onClick={() => setOpen((now) => !now)}
        >
          <ChevronDown
            aria-hidden
            className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`}
          />
          Details, tests and history
        </Button>
      </div>
      {open && <MetricDetails spaceId={spaceId} item={item} editor={editor} />}
      {remove.error && (
        <Notice tone="error" title="Not removed">
          {asApiError(remove.error).message}
        </Notice>
      )}
    </li>
  );
}
