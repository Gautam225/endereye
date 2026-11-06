import {
  ArrowRight,
  Check,
  ChevronRight,
  Link2,
  RefreshCw,
  Search,
  Sparkles,
  Table2,
  Trash2,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { BareInput, BareTextArea, SelectField, TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { count, plural, rowsText, timeAgo } from "../../lib/format";
import { RELATIONSHIPS, columnChange, editOf, parseSynonyms, type ColumnEdit } from "./metadata";
import {
  useCreateJoin,
  useDeleteJoin,
  useDetectJoins,
  useDraftTable,
  useJoins,
  useMetadata,
  useProfileTable,
  useSetTableDescription,
  useTables,
  useUpdateColumn,
  useUpdateJoin,
  useValueSearch,
} from "./queries";
import type { ColumnMeta, ColumnStats, Join, Relationship, Space, TableMeta } from "./types";

const EASE = [0.16, 1, 0.3, 1] as const;

/** What the AI is told about the space's data: descriptions, statistics, searchable values, joins. */
export function MetadataTab({ space }: { space: Space }) {
  const editor = space.my_role === "editor";
  const metadata = useMetadata(space.id);
  const sources = useTables(space.id);
  // Tables of a database are not profiled (their values are not read) and their joins come
  // from the database's own foreign keys.
  const external = sources.data?.some((table) => table.source_type === "external") ?? false;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Tables and columns"
          description={
            editor
              ? "Descriptions and synonyms help the AI pick the right columns. They are kept here and never change your data."
              : "What the AI knows about this space's data."
          }
        />
        {metadata.isPending ? (
          <div className="space-y-3 p-5">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : metadata.isError ? (
          <div className="p-5">
            <Notice tone="error" title="Could not load the metadata">
              {metadata.error.message}
            </Notice>
          </div>
        ) : metadata.data.length === 0 ? (
          <EmptyState icon={Table2} title="No tables yet">
            Add a table on the Data tab; it is profiled automatically.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {metadata.data.map((table) => (
              <TableCard
                key={table.id}
                spaceId={space.id}
                table={table}
                editor={editor}
                external={external}
              />
            ))}
          </ul>
        )}
      </Card>

      {metadata.data && metadata.data.length > 1 && (
        <JoinsCard spaceId={space.id} tables={metadata.data} editor={editor} external={external} />
      )}
      {metadata.data && metadata.data.length > 0 && <ValueTester spaceId={space.id} />}
    </div>
  );
}

// ── Tables ───────────────────────────────────────────────────────────────────

function TableCard({
  spaceId,
  table,
  editor,
  external,
}: {
  spaceId: string;
  table: TableMeta;
  editor: boolean;
  external: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState(table.description);
  const [edits, setEdits] = useState<Record<string, ColumnEdit>>({});
  const profile = useProfileTable(spaceId);
  const draft = useDraftTable(spaceId);
  const saveTable = useSetTableDescription(spaceId);
  const saveColumn = useUpdateColumn(spaceId);
  const [saveError, setSaveError] = useState<string | null>(null);

  const changes = table.columns.flatMap((column) => {
    const change = columnChange(column, edits[column.id]);
    return Object.keys(change).length > 0 ? [{ column, change }] : [];
  });
  const descriptionChanged = description.trim() !== table.description;
  const pending = changes.length + (descriptionChanged ? 1 : 0);
  const busy = saveTable.isPending || saveColumn.isPending;
  const problem = [profile.error, draft.error]
    .map((error) => (error ? asApiError(error).message : null))
    .find(Boolean);

  function editColumn(column: ColumnMeta, part: Partial<ColumnEdit>) {
    setEdits((current) => ({
      ...current,
      [column.id]: { ...(current[column.id] ?? editOf(column)), ...part },
    }));
  }

  function fillFromDraft() {
    draft.mutate(table.id, {
      onSuccess: (result) => {
        // Only blanks are filled, so nothing an editor wrote is lost.
        if (!description.trim()) setDescription(result.description);
        setEdits((current) => {
          const next = { ...current };
          for (const suggestion of result.columns) {
            const column = table.columns.find((c) => c.name === suggestion.name);
            if (!column) continue;
            const edit = next[column.id] ?? editOf(column);
            next[column.id] = {
              description: edit.description.trim() ? edit.description : suggestion.description,
              synonyms: edit.synonyms.trim() ? edit.synonyms : suggestion.synonyms.join(", "),
            };
          }
          return next;
        });
        setOpen(true);
      },
    });
  }

  async function save() {
    setSaveError(null);
    try {
      if (descriptionChanged) {
        await saveTable.mutateAsync({ tableId: table.id, description: description.trim() });
      }
      await Promise.all(
        changes.map(({ column, change }) =>
          saveColumn.mutateAsync({ tableId: table.id, columnId: column.id, change }),
        ),
      );
      setEdits({});
    } catch (caught) {
      setSaveError(asApiError(caught).message);
    }
  }

  return (
    <li>
      <div className="flex flex-wrap items-center gap-3 px-5 py-3">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex min-w-0 flex-1 items-center gap-3 rounded-md text-left"
        >
          <ChevronRight
            aria-hidden
            className={cn(
              "size-4 shrink-0 text-subtle transition-transform duration-200",
              open && "rotate-90",
            )}
          />
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2">
              <span className="truncate font-mono text-[13.5px] font-medium">{table.name}</span>
              {table.profiled_at === null && <Badge tone="warn">Not profiled</Badge>}
              {table.stale && <Badge tone="warn">Data changed</Badge>}
              {pending > 0 && <Badge tone="accent">Unsaved</Badge>}
            </span>
            <span className="block truncate text-[12.5px] text-subtle">
              {table.description || "No description yet"} · {rowsText(table.row_count, external)}
              {table.profiled_at && ` · profiled ${timeAgo(table.profiled_at)}`}
            </span>
          </span>
        </button>
        {editor && (
          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              loading={draft.isPending}
              onClick={fillFromDraft}
              title="The AI suggests descriptions and synonyms for blank fields. Nothing is saved until you save."
            >
              <Sparkles aria-hidden className="size-3.5" />
              Draft with AI
            </Button>
            {!external && (
              <Button
                size="sm"
                variant={table.stale ? "primary" : "secondary"}
                loading={profile.isPending}
                onClick={() => profile.mutate(table.id)}
                title="Read the table again: statistics and searchable values"
              >
                <RefreshCw aria-hidden className="size-3.5" />
                {table.profiled_at === null ? "Profile" : "Re-profile"}
              </Button>
            )}
          </div>
        )}
      </div>
      {problem && (
        <Notice tone="error" title="That didn't work" className="mx-5 mb-3">
          {problem}
        </Notice>
      )}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="space-y-4 px-5 pb-5 sm:pl-12">
              <div className="space-y-1.5">
                <label
                  htmlFor={`desc-${table.id}`}
                  className="block text-[12.5px] font-medium text-muted"
                >
                  What one row of this table is
                </label>
                {editor ? (
                  <BareTextArea
                    id={`desc-${table.id}`}
                    rows={2}
                    maxLength={1000}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="e.g. One row per customer order, including cancelled ones"
                  />
                ) : (
                  <p className="text-[13.5px]">{table.description || "No description."}</p>
                )}
              </div>
              {table.columns.length === 0 ? (
                <p className="text-[13px] text-muted">This table has not been profiled yet.</p>
              ) : (
                <ul className="divide-y divide-border rounded-md border border-border">
                  {table.columns.map((column) => (
                    <ColumnRow
                      key={column.id}
                      spaceId={spaceId}
                      tableId={table.id}
                      column={column}
                      editor={editor}
                      external={external}
                      edit={edits[column.id] ?? editOf(column)}
                      onEdit={(part) => editColumn(column, part)}
                      onToggleError={setSaveError}
                    />
                  ))}
                </ul>
              )}
              {saveError && (
                <Notice tone="error" title="Not saved">
                  {saveError}
                </Notice>
              )}
              {editor && (
                <div className="flex items-center justify-end gap-3">
                  {pending > 0 && (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setDescription(table.description);
                        setEdits({});
                        setSaveError(null);
                      }}
                    >
                      Discard
                    </Button>
                  )}
                  <Button variant="primary" disabled={pending === 0} loading={busy} onClick={save}>
                    Save {pending > 0 ? plural(pending, "change") : "changes"}
                  </Button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

function statsLine(stats: ColumnStats | null): string {
  if (!stats) return "Not profiled";
  const parts = [
    `${stats.null_pct}% empty`,
    stats.distinct_count === null ? null : `${count(stats.distinct_count)} distinct`,
    stats.min !== null && stats.max !== null && stats.min !== stats.max
      ? `${stats.min} to ${stats.max}`
      : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

function ColumnRow({
  spaceId,
  tableId,
  column,
  editor,
  external,
  edit,
  onEdit,
  onToggleError,
}: {
  spaceId: string;
  tableId: string;
  column: ColumnMeta;
  editor: boolean;
  external: boolean;
  edit: ColumnEdit;
  onEdit: (part: Partial<ColumnEdit>) => void;
  onToggleError: (message: string | null) => void;
}) {
  const update = useUpdateColumn(spaceId);
  const searchable = column.stats?.searchable ?? false;
  const common = column.stats?.top_values ?? [];

  function toggle(change: { hidden?: boolean; share_values?: boolean; entity_matching?: boolean }) {
    onToggleError(null);
    update.mutate(
      { tableId, columnId: column.id, change },
      { onError: (caught) => onToggleError(asApiError(caught).message) },
    );
  }

  return (
    <li className={cn("space-y-2 px-4 py-3", column.hidden && "bg-surface-2/50")}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono text-[13px] font-medium">{column.name}</span>
        <span className="font-mono text-[12px] text-subtle">{column.type.toLowerCase()}</span>
        {column.hidden && <Badge>Hidden from AI</Badge>}
        {column.entity_matching && column.indexed_values > 0 && (
          <Badge tone="accent">{count(column.indexed_values)} searchable values</Badge>
        )}
      </div>
      <p className="text-[12.5px] text-subtle">
        {external ? "Values are not read from the database" : statsLine(column.stats)}
        {column.share_values && common.length > 0 && (
          <>
            {" · common: "}
            {common.map((item) => `${item.value} (${count(item.count)})`).join(", ")}
          </>
        )}
      </p>
      {editor ? (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            <BareInput
              aria-label={`Description of ${column.name}`}
              maxLength={1000}
              placeholder="What this column means"
              value={edit.description}
              onChange={(event) => onEdit({ description: event.target.value })}
            />
            <BareInput
              aria-label={`Synonyms of ${column.name}, separated by commas`}
              placeholder="Synonyms, separated by commas"
              value={edit.synonyms}
              onChange={(event) => onEdit({ synonyms: event.target.value })}
              aria-invalid={parseSynonyms(edit.synonyms).length > 20 ? true : undefined}
            />
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-1.5">
            <Toggle
              label={external ? "Hide from AI and block in SQL" : "Hide from AI"}
              checked={column.hidden}
              disabled={update.isPending}
              onChange={(checked) => toggle({ hidden: checked })}
            />
            {!external && (
              <>
                <Toggle
                  label="Show sample values to AI"
                  checked={column.share_values}
                  disabled={update.isPending}
                  onChange={(checked) => toggle({ share_values: checked })}
                />
                <Toggle
                  label="Searchable values"
                  checked={column.entity_matching}
                  disabled={update.isPending || !column.share_values || !searchable}
                  title={
                    searchable
                      ? "Lets the AI match what people type to the real values, even with typos"
                      : "Only text columns with at most 1,024 distinct values (each up to 127 characters)"
                  }
                  onChange={(checked) => toggle({ entity_matching: checked })}
                />
              </>
            )}
          </div>
        </>
      ) : (
        (column.description || column.synonyms.length > 0) && (
          <p className="text-[13px]">
            {column.description}
            {column.synonyms.length > 0 && (
              <span className="text-subtle"> Also called: {column.synonyms.join(", ")}.</span>
            )}
          </p>
        )
      )}
    </li>
  );
}

function Toggle({
  label,
  checked,
  disabled,
  title,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  title?: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label
      title={title}
      className={cn(
        "inline-flex items-center gap-2 text-[12.5px]",
        disabled ? "text-subtle" : "cursor-pointer text-muted hover:text-fg",
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="size-3.5 accent-[var(--color-accent)]"
      />
      {label}
    </label>
  );
}

// ── Joins ────────────────────────────────────────────────────────────────────

function JoinsCard({
  spaceId,
  tables,
  editor,
  external,
}: {
  spaceId: string;
  tables: TableMeta[];
  editor: boolean;
  external: boolean;
}) {
  const joins = useJoins(spaceId);
  const detect = useDetectJoins(spaceId);
  const error = detect.error ? asApiError(detect.error).message : null;

  return (
    <Card>
      <CardHeader
        title="Joins"
        description={
          external
            ? "How the tables connect. Foreign keys declared in the database are used as confirmed joins; add any other join by hand."
            : "How the tables connect, so the AI writes correct JOINs. Detected joins should be confirmed."
        }
        aside={
          editor &&
          !external && (
            <Button size="sm" loading={detect.isPending} onClick={() => detect.mutate()}>
              <Link2 aria-hidden className="size-3.5" />
              Find joins
            </Button>
          )
        }
      />
      {error && (
        <Notice tone="error" title="Could not look for joins" className="m-5">
          {error}
        </Notice>
      )}
      {detect.data && detect.data.length === 0 && (
        <p role="status" className="px-5 pt-4 text-[13px] text-muted">
          No new joins found.
        </p>
      )}
      {joins.isPending ? (
        <Skeleton className="m-5 h-12" />
      ) : joins.isError ? (
        <Notice tone="error" title="Could not load joins" className="m-5">
          {joins.error.message}
        </Notice>
      ) : joins.data.length === 0 ? (
        <p className="px-5 py-6 text-[13px] text-muted">
          No joins yet. {editor && "Use Find joins, or add one below."}
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {joins.data.map((join) => (
            <JoinRow key={join.id} spaceId={spaceId} join={join} editor={editor} />
          ))}
        </ul>
      )}
      {editor && <AddJoin spaceId={spaceId} tables={tables} />}
    </Card>
  );
}

function JoinRow({ spaceId, join, editor }: { spaceId: string; join: Join; editor: boolean }) {
  const update = useUpdateJoin(spaceId);
  const remove = useDeleteJoin(spaceId);
  const label = RELATIONSHIPS.find((r) => r.value === join.relationship)?.label;
  const failure = update.error ?? remove.error;

  return (
    <li className="space-y-2 px-5 py-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 font-mono text-[13px]">
          <span>
            {join.left_table}.{join.left_column}
          </span>
          <ArrowRight aria-hidden className="size-3.5 text-subtle" />
          <span>
            {join.right_table}.{join.right_column}
          </span>
        </p>
        {join.confirmed ? (
          <Badge tone="ok">Confirmed</Badge>
        ) : (
          <Badge tone="warn">Needs review</Badge>
        )}
        {editor ? (
          <SelectField
            label={`Relationship of ${join.left_table} to ${join.right_table}`}
            hideLabel
            value={join.relationship}
            options={RELATIONSHIPS}
            className="h-8 w-36 text-[13px]"
            onChange={(event) =>
              update.mutate({
                joinId: join.id,
                change: { relationship: event.target.value as Relationship },
              })
            }
          />
        ) : (
          <span className="text-[13px] text-muted">{label}</span>
        )}
        {editor && (
          <div className="flex items-center gap-1">
            {!join.confirmed && (
              <Button
                size="sm"
                loading={update.isPending}
                onClick={() => update.mutate({ joinId: join.id, change: { confirmed: true } })}
              >
                <Check aria-hidden className="size-3.5" />
                Confirm
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove join ${join.left_table}.${join.left_column} to ${join.right_table}.${join.right_column}`}
              loading={remove.isPending}
              onClick={() => remove.mutate(join.id)}
            >
              <Trash2 aria-hidden />
            </Button>
          </div>
        )}
      </div>
      {failure && (
        <Notice tone="error" title="That didn't work">
          {asApiError(failure).message}
        </Notice>
      )}
    </li>
  );
}

function AddJoin({ spaceId, tables }: { spaceId: string; tables: TableMeta[] }) {
  const create = useCreateJoin(spaceId);
  const [leftId, setLeftId] = useState("");
  const [leftColumn, setLeftColumn] = useState("");
  const [rightId, setRightId] = useState("");
  const [rightColumn, setRightColumn] = useState("");
  const [relationship, setRelationship] = useState<Relationship>("many_to_one");
  const error = create.error ? asApiError(create.error).message : null;

  const tableOptions = [
    { value: "", label: "Choose a table" },
    ...tables.map((t) => ({ value: t.id, label: t.name })),
  ];
  const columnOptions = (tableId: string) => [
    { value: "", label: "Choose a column" },
    ...(tables
      .find((t) => t.id === tableId)
      ?.columns.map((c) => ({
        value: c.name,
        label: c.name,
      })) ?? []),
  ];
  const ready = leftId && leftColumn && rightId && rightColumn && leftId !== rightId;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    create.mutate(
      {
        left_table_id: leftId,
        left_column: leftColumn,
        right_table_id: rightId,
        right_column: rightColumn,
        relationship,
      },
      {
        onSuccess: () => {
          setLeftId("");
          setLeftColumn("");
          setRightId("");
          setRightColumn("");
        },
      },
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3 border-t border-border p-5">
      <p className="text-[13px] font-medium">Add a join</p>
      {error && (
        <Notice tone="error" title="Not added">
          {error}
        </Notice>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <SelectField
          label="Left table"
          value={leftId}
          options={tableOptions}
          onChange={(event) => {
            setLeftId(event.target.value);
            setLeftColumn("");
          }}
        />
        <SelectField
          label="Left column"
          value={leftColumn}
          options={columnOptions(leftId)}
          disabled={!leftId}
          onChange={(event) => setLeftColumn(event.target.value)}
        />
        <SelectField
          label="Right table"
          value={rightId}
          options={tableOptions}
          onChange={(event) => {
            setRightId(event.target.value);
            setRightColumn("");
          }}
        />
        <SelectField
          label="Right column"
          value={rightColumn}
          options={columnOptions(rightId)}
          disabled={!rightId}
          onChange={(event) => setRightColumn(event.target.value)}
        />
        <SelectField
          label="Relationship"
          value={relationship}
          options={RELATIONSHIPS}
          onChange={(event) => setRelationship(event.target.value as Relationship)}
        />
      </div>
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={create.isPending} disabled={!ready}>
          Add join
        </Button>
      </div>
    </form>
  );
}

// ── Search tester ────────────────────────────────────────────────────────────

function ValueTester({ spaceId }: { spaceId: string }) {
  const [text, setText] = useState("");
  const [settled, setSettled] = useState("");
  const search = useValueSearch(spaceId, settled);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(text.trim()), 250);
    return () => clearTimeout(timer);
  }, [text]);

  return (
    <Card>
      <CardHeader
        title="Try a value"
        description="Type a word as a person might, typos included, and see which real values the AI would match it to."
      />
      <div className="space-y-3 p-5">
        <TextField
          label="Search the searchable values"
          placeholder="e.g. Gujrat"
          maxLength={127}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        {settled &&
          (search.isError ? (
            <Notice tone="error" title="Search failed">
              {search.error.message}
            </Notice>
          ) : search.data && search.data.length === 0 ? (
            <p role="status" className="flex items-center gap-2 text-[13px] text-muted">
              <Search aria-hidden className="size-3.5" />
              No searchable value looks like that.
            </p>
          ) : (
            <ul className="divide-y divide-border rounded-md border border-border">
              {search.data?.map((match) => (
                <li
                  key={`${match.table}.${match.column}.${match.value}`}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-[13px]"
                >
                  <span className="min-w-0 truncate">
                    <span className="font-medium">{match.value}</span>{" "}
                    <span className="font-mono text-[12px] text-subtle">
                      {match.table}.{match.column}
                    </span>
                  </span>
                  <span className="shrink-0 text-[12px] text-subtle">
                    {Math.round(match.score * 100)}% match
                  </span>
                </li>
              ))}
            </ul>
          ))}
      </div>
    </Card>
  );
}
