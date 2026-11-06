import {
  ChevronRight,
  Columns3,
  Database,
  Eye,
  Link2,
  MessageSquare,
  RefreshCw,
  Rows3,
  Search,
  Table2,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { Button } from "../../components/ui/Button";
import { BareInput, SelectField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge, StatusLabel } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { plural } from "../../lib/format";
import { useConnections } from "../connections/queries";
import type { Connection } from "../connections/types";
import {
  MAX_EXTERNAL_TABLES,
  describeChange,
  filterTables,
  groupBySchema,
  hasChanges,
  refOf,
  roomLeft,
  selectableRefs,
  sizeText,
} from "./externalTables";
import { useAttachTables, useExternalSchema, useRefreshTables } from "./queries";
import type { AttachResult, DataTable, ExternalTable } from "./types";

/**
 * Choosing which tables of an external database this space may use, and keeping them in step
 * with the database. Administrators only: what the connection's login can read is listed, and
 * an admin decides which of it a space gets. Nothing is copied; only descriptions are stored.
 */
export function ExternalTablesPanel({
  spaceId,
  external,
}: {
  spaceId: string;
  external: DataTable[];
}) {
  const connections = useConnections();
  const lockedTo = external[0]?.connection_id ?? null;
  const usable = (connections.data ?? []).filter(
    (connection) => connection.id === lockedTo || connection.status === "ok",
  );
  // The Connections page can send people here with its connection already chosen.
  const [params] = useSearchParams();
  const [chosen, setChosen] = useState(params.get("connection") ?? "");
  const connectionId =
    lockedTo ?? (usable.some((c) => c.id === chosen) ? chosen : (usable[0]?.id ?? ""));
  const connection = usable.find((c) => c.id === connectionId);

  return (
    <div className="space-y-5">
      {connections.isPending ? (
        <Skeleton className="h-16" />
      ) : connections.isError ? (
        <Notice tone="error" title="Could not load the connections">
          {connections.error.message}
        </Notice>
      ) : usable.length === 0 || !connection ? (
        <Notice title="No working connection yet">
          Add a connection and press Test on the{" "}
          <Link to="/connections" className="font-medium text-accent underline">
            Connections page
          </Link>
          . A connection can be used once a test shows its login is read-only.
        </Notice>
      ) : (
        <>
          {lockedTo === null && usable.length > 1 && (
            <SelectField
              label="Connection"
              value={connectionId}
              onChange={(event) => setChosen(event.target.value)}
              options={usable.map((c) => ({ value: c.id, label: `${c.name} (${c.database})` }))}
            />
          )}
          <ConnectionStrip connection={connection} locked={lockedTo !== null} />
          <Picker spaceId={spaceId} connectionId={connectionId} attached={external.length} />
        </>
      )}
      {external.length > 0 && <Refresh spaceId={spaceId} />}
    </div>
  );
}

/** Which database the tables come from, and that its login is read-only. */
function ConnectionStrip({ connection, locked }: { connection: Connection; locked: boolean }) {
  return (
    <div>
      <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-2/40 px-3.5 py-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
          <Database aria-hidden className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-medium">{connection.name}</p>
          <p className="truncate font-mono text-[12px] text-subtle">
            {connection.database} · {connection.host}:{connection.port}
          </p>
        </div>
        <StatusLabel tone="ok">Read-only</StatusLabel>
      </div>
      {locked && (
        <p className="mt-2 text-[12.5px] text-subtle">
          A space uses one database, and cannot mix it with uploaded files.
        </p>
      )}
    </div>
  );
}

// ── Choosing tables ──────────────────────────────────────────────────────────

function Picker({
  spaceId,
  connectionId,
  attached,
}: {
  spaceId: string;
  connectionId: string;
  attached: number;
}) {
  const schema = useExternalSchema(connectionId, spaceId);
  const attach = useAttachTables(spaceId);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [added, setAdded] = useState<AttachResult | null>(null);
  const error = attach.error ? asApiError(attach.error) : null;
  const room = roomLeft(attached, picked.size);

  if (schema.isPending) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-9" />
        <Skeleton className="h-52" />
      </div>
    );
  }
  if (schema.isError) {
    return (
      <Notice tone="error" title="Could not read the database">
        {asApiError(schema.error).message}
      </Notice>
    );
  }

  const readable = schema.data;
  const shown = filterTables(readable, query);
  const groups = groupBySchema(shown);
  const toAdd = selectableRefs(shown, picked, attached);
  const toggle = (ref: string, set: Set<string>, update: (s: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(ref)) next.delete(ref);
    else next.add(ref);
    update(next);
  };

  function submit() {
    const tables = readable
      .filter((table) => picked.has(refOf(table)))
      .map(({ schema: schemaName, name }) => ({ schema: schemaName, name }));
    attach.mutate(
      { connection_id: connectionId, tables },
      {
        onSuccess: (result) => {
          setAdded(result);
          setPicked(new Set());
        },
      },
    );
  }

  return (
    <div className="space-y-3">
      {added && (
        <Notice
          title={`Added ${plural(added.tables.length, "table")}`}
          action={
            <div className="flex items-center gap-2">
              <Link
                to={`/spaces/${spaceId}/chat`}
                className="inline-flex h-8 items-center gap-1.5 rounded-md bg-accent px-2.5 text-[13px] font-medium text-accent-fg shadow-card transition-colors hover:bg-accent/90"
              >
                <MessageSquare aria-hidden className="size-3.5" />
                Start chatting
              </Link>
              <Button size="sm" variant="ghost" onClick={() => setAdded(null)}>
                Dismiss
              </Button>
            </div>
          }
        >
          {added.joins_created > 0
            ? `${plural(added.joins_created, "join")} taken from the database's foreign keys.`
            : "No joins were found between them."}
          {added.skipped_foreign_keys.length > 0 &&
            ` A foreign key over several columns can't be used as a join: ${added.skipped_foreign_keys.join(", ")}.`}
        </Notice>
      )}
      {error && (
        <Notice tone="error" title="Could not add the tables">
          {error.message}
        </Notice>
      )}

      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle"
        />
        <BareInput
          type="text"
          aria-label="Search tables"
          placeholder="Search tables by name, schema or description"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="pr-9 pl-9"
        />
        {query && (
          <button
            type="button"
            aria-label="Clear the search"
            onClick={() => setQuery("")}
            className="absolute top-1/2 right-2 grid size-6 -translate-y-1/2 place-items-center rounded text-subtle transition-colors hover:bg-surface-2 hover:text-fg"
          >
            <X aria-hidden className="size-3.5" />
          </button>
        )}
      </div>

      {readable.length === 0 ? (
        <div className="rounded-lg border border-border">
          <EmptyState icon={Table2} title="The login can't read any table">
            Grant it SELECT on the tables to analyse, then open this page again.
          </EmptyState>
        </div>
      ) : shown.length === 0 ? (
        <div className="rounded-lg border border-border px-4 py-8 text-center text-[13px] text-muted">
          No table matches &quot;{query}&quot;.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border">
          <div className="flex items-center justify-between gap-3 border-b border-border bg-surface-2/50 px-3.5 py-1.5">
            <p className="text-[12.5px] text-muted">
              {plural(shown.length, "table")}
              {groups.length > 1 && ` in ${plural(groups.length, "schema")}`}
            </p>
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="ghost"
                disabled={toAdd.length === 0}
                onClick={() => setPicked(new Set([...picked, ...toAdd]))}
              >
                Select all
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={picked.size === 0}
                onClick={() => setPicked(new Set())}
              >
                Clear
              </Button>
            </div>
          </div>
          <div className="max-h-[26rem] overflow-y-auto">
            {groups.map((group) => (
              <section key={group.schema} aria-label={`Schema ${group.schema}`}>
                <h4 className="sticky top-0 z-10 flex items-center gap-2 border-b border-border bg-surface-2 px-3.5 py-1.5 text-[11px] font-semibold tracking-wide text-subtle uppercase">
                  {group.schema}
                  <span className="font-normal tracking-normal normal-case">
                    {plural(group.tables.length, "table")}
                  </span>
                </h4>
                <ul className="divide-y divide-border">
                  {group.tables.map((table) => {
                    const ref = refOf(table);
                    return (
                      <TableChoice
                        key={ref}
                        table={table}
                        picked={picked.has(ref)}
                        expanded={open.has(ref)}
                        disabled={table.attached_here || (!picked.has(ref) && room === 0)}
                        onPick={() => toggle(ref, picked, setPicked)}
                        onExpand={() => toggle(ref, open, setOpen)}
                      />
                    );
                  })}
                </ul>
              </section>
            ))}
          </div>
        </div>
      )}

      <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface-2 px-4 py-3 shadow-card">
        <p className="text-[12.5px] text-muted" aria-live="polite">
          {picked.size > 0 ? (
            <>
              <span className="font-medium text-fg">{picked.size} selected</span>
              {room > 0
                ? ` · room for ${room} more`
                : ` · the limit of ${MAX_EXTERNAL_TABLES} is reached`}
            </>
          ) : (
            "Tick the tables this space should use."
          )}
        </p>
        <Button
          variant="primary"
          disabled={picked.size === 0}
          loading={attach.isPending}
          onClick={submit}
        >
          {picked.size > 0 ? `Add ${plural(picked.size, "table")}` : "Add tables"}
        </Button>
      </div>
    </div>
  );
}

function Fact({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon aria-hidden className="size-3.5 text-subtle" />
      {children}
    </span>
  );
}

function TableChoice({
  table,
  picked,
  expanded,
  disabled,
  onPick,
  onExpand,
}: {
  table: ExternalTable;
  picked: boolean;
  expanded: boolean;
  disabled: boolean;
  onPick: () => void;
  onExpand: () => void;
}) {
  const ref = refOf(table);
  const KindIcon = table.kind === "table" ? Table2 : Eye;
  return (
    <li
      className={cn(
        "border-l-2 border-transparent transition-colors",
        picked && "border-accent bg-accent-soft/40",
        table.attached_here && "bg-surface-2/40",
      )}
    >
      <div className="flex items-start gap-2 px-3.5 py-3">
        <label
          className={cn(
            "flex min-w-0 flex-1 items-start gap-3",
            disabled ? "cursor-not-allowed" : "cursor-pointer",
          )}
        >
          <input
            type="checkbox"
            checked={picked || table.attached_here}
            disabled={disabled}
            onChange={onPick}
            aria-label={`Use ${ref}`}
            className="mt-0.5 size-4 shrink-0 accent-[var(--color-accent)]"
          />
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <KindIcon aria-hidden className="size-4 shrink-0 text-subtle" />
              <span className="font-mono text-[13.5px]">
                <span className="text-subtle">{table.schema}.</span>
                <span className="font-medium">{table.name}</span>
              </span>
              {table.kind !== "table" && <Badge>{table.kind}</Badge>}
              {table.attached_here && <Badge tone="ok">In this space</Badge>}
            </span>
            <span className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-muted">
              <Fact icon={Columns3}>{plural(table.columns.length, "column")}</Fact>
              <Fact icon={Rows3}>{sizeText(table.estimated_rows)}</Fact>
              {table.foreign_keys.length > 0 && (
                <Fact icon={Link2}>{plural(table.foreign_keys.length, "relationship")}</Fact>
              )}
            </span>
            {table.comment && (
              <span className="mt-1.5 block text-[13px] text-muted">{table.comment}</span>
            )}
          </span>
        </label>
        <Button
          size="icon"
          variant="ghost"
          aria-expanded={expanded}
          aria-label={`${expanded ? "Hide" : "Show"} the columns of ${ref}`}
          onClick={onExpand}
        >
          <ChevronRight
            aria-hidden
            className={cn("transition-transform duration-200", expanded && "rotate-90")}
          />
        </Button>
      </div>
      {expanded && (
        <div className="space-y-3 border-t border-border bg-surface-2/40 py-3 pr-4 pl-[3.25rem]">
          <div>
            <p className="mb-1 text-[11px] font-semibold tracking-wide text-subtle uppercase">
              Columns
            </p>
            <ul className="divide-y divide-border/60">
              {table.columns.map((column) => (
                <li
                  key={column.name}
                  className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-1.5"
                >
                  <span className="min-w-0">
                    <span className="font-mono text-[12.5px] font-medium">{column.name}</span>
                    {column.comment && (
                      <span className="ml-2 text-[12.5px] text-muted">{column.comment}</span>
                    )}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-[12px] text-subtle">{column.type}</span>
                    {column.primary_key && <Badge tone="accent">key</Badge>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          {table.foreign_keys.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] font-semibold tracking-wide text-subtle uppercase">
                Relationships
              </p>
              <ul className="space-y-1 text-[12.5px] text-muted">
                {table.foreign_keys.map((fk) => (
                  <li key={fk.name}>
                    <span className="font-mono text-fg">{fk.columns.join(", ")}</span> refers to{" "}
                    <span className="font-mono text-fg">
                      {fk.ref_schema}.{fk.ref_table}
                    </span>{" "}
                    ({fk.ref_columns.join(", ")})
                    {!fk.supported && " · over several columns, not used as a join"}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

// ── Keeping up with the database ─────────────────────────────────────────────

function Refresh({ spaceId }: { spaceId: string }) {
  const refresh = useRefreshTables(spaceId);
  const [applying, setApplying] = useState(false);
  const result = refresh.data;
  const error = refresh.error ? asApiError(refresh.error) : null;

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface-2/30">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5">
        <div className="flex min-w-0 items-start gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-md bg-surface-2 text-muted">
            <RefreshCw aria-hidden className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="text-[14px] font-medium">Keep in step with the database</p>
            <p className="text-[12.5px] text-muted">
              Finds new, removed or retyped columns and changed foreign keys. Nothing changes until
              you apply it, and your descriptions and joins are kept.
            </p>
          </div>
        </div>
        <Button
          loading={refresh.isPending && !applying}
          onClick={() => {
            setApplying(false);
            refresh.mutate(false);
          }}
        >
          Check for changes
        </Button>
      </div>
      {(error || result) && (
        <div className="space-y-3 border-t border-border px-4 py-3.5">
          {error && (
            <Notice tone="error" title="Could not check the database">
              {error.message}
            </Notice>
          )}
          {result &&
            (!hasChanges(result) ? (
              <p role="status" className="text-[13px] text-muted">
                {result.applied ? "The changes were applied." : "Everything is up to date."}
              </p>
            ) : (
              <>
                <ul className="divide-y divide-border rounded-md border border-border bg-surface">
                  {result.tables
                    .filter((table) => table.status !== "unchanged")
                    .map((table) => (
                      <li key={table.ref} className="px-3 py-2.5">
                        <p className="flex items-center gap-2 font-mono text-[13px] font-medium">
                          {table.ref}
                          <Badge tone={table.status === "missing" ? "error" : "warn"}>
                            {table.status === "missing" ? "Missing" : "Changed"}
                          </Badge>
                        </p>
                        <p className="text-[12.5px] text-muted">{describeChange(table)}</p>
                      </li>
                    ))}
                </ul>
                <p className="text-[12.5px] text-muted">
                  {result.joins_added > 0 &&
                    `${plural(result.joins_added, "join")} would be added. `}
                  {result.joins_removed > 0 &&
                    `${plural(result.joins_removed, "join")} would be removed (their foreign key is gone). `}
                  {result.applied && "These changes have been applied."}
                </p>
                {!result.applied && (
                  <div className="flex justify-end">
                    <Button
                      variant="primary"
                      loading={refresh.isPending && applying}
                      onClick={() => {
                        setApplying(true);
                        refresh.mutate(true);
                      }}
                    >
                      Apply these changes
                    </Button>
                  </div>
                )}
              </>
            ))}
        </div>
      )}
    </section>
  );
}
