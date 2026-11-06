import {
  ChevronRight,
  Database,
  DatabaseZap,
  FileSpreadsheet,
  FileUp,
  FolderTree,
  Plus,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState, type DragEvent, type FormEvent, type ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { TextField } from "../../components/ui/Field";
import { InlineCode } from "../../components/ui/InlineCode";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fileSize, plural, rowsText, timeAgo } from "../../lib/format";
import { useAuth } from "../../lib/auth";
import { ExternalTablesPanel } from "./ExternalTablesCard";
import { MAX_EXTERNAL_TABLES } from "./externalTables";
import {
  useAddDeltaTable,
  useDataLimits,
  useDeleteTable,
  usePreview,
  useTables,
  useUploadTable,
} from "./queries";
import { suggestTableName } from "./names";
import { ResultTable } from "./ResultTable";
import type { DataTable, Space } from "./types";

const EASE = [0.16, 1, 0.3, 1] as const;

export function DataTab({ space }: { space: Space }) {
  const editor = space.my_role === "editor";
  const tables = useTables(space.id);
  const { hasRole } = useAuth();
  // A space uses uploaded files, or the tables of one database, never both.
  const external = (tables.data ?? []).filter((table) => table.source_type === "external");
  const hasFiles = (tables.data ?? []).some((table) => table.source_type !== "external");

  const sources: Source[] = [];
  if (editor && external.length === 0) sources.push("upload", "delta");
  if (hasRole("admin") && !hasFiles && tables.data) sources.push("database");
  const filled = (tables.data?.length ?? 0) > 0;
  // With nothing yet, adding data is the first step and is open. Afterwards the tables lead and
  // adding is one button away, so the big drop area is not always in the way.
  const [open, setOpen] = useState(false);
  const canAdd = sources.length > 0;
  const showAdd = canAdd && (!filled || open);

  return (
    <div className="space-y-6">
      {showAdd && (
        <AddData
          spaceId={space.id}
          sources={sources}
          external={external}
          filled={filled}
          onClose={filled ? () => setOpen(false) : undefined}
        />
      )}
      <Card className="rounded-xl">
        <CardHeader
          title={
            <>
              Tables
              {tables.data && tables.data.length > 0 && <Badge>{tables.data.length}</Badge>}
            </>
          }
          description={
            editor
              ? "These names are what SQL uses. Uploaded files are stored as Parquet; Delta and database tables are read where they are."
              : "The data this space answers questions from."
          }
          aside={
            filled &&
            canAdd &&
            !open && (
              <Button size="sm" variant="primary" onClick={() => setOpen(true)}>
                <Plus aria-hidden />
                Add data
              </Button>
            )
          }
        />
        {tables.isPending ? (
          <div className="space-y-3 p-5">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : tables.isError ? (
          <div className="p-5">
            <Notice tone="error" title="Could not load tables">
              {tables.error.message}
            </Notice>
          </div>
        ) : tables.data.length === 0 ? (
          <EmptyState icon={Database} title="No tables yet">
            {editor
              ? "Upload a file or add a Delta table above, or (admins) pick tables from a database."
              : "An editor hasn't added data yet."}
          </EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {tables.data.map((table) => (
              <TableRow key={table.id} spaceId={space.id} table={table} editor={editor} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

// ── Adding data ──────────────────────────────────────────────────────────────

type Source = "upload" | "delta" | "database";

const SOURCES: Record<Source, { label: string; icon: ReactNode; about: string }> = {
  upload: {
    label: "Upload a file",
    icon: <FileUp aria-hidden />,
    about: "A CSV, Excel, Parquet or JSON file becomes a table you can ask about.",
  },
  delta: {
    label: "Delta folder",
    icon: <FolderTree aria-hidden />,
    about: "A Delta Lake folder on the server is read where it is; nothing is copied.",
  },
  database: {
    label: "Database",
    icon: <DatabaseZap aria-hidden />,
    about: `Choose the tables this space may use (up to ${MAX_EXTERNAL_TABLES}). Only descriptions are kept here; rows stay in the database and are read when a question is asked.`,
  },
};

/** One card for every way of adding data: pick where it comes from, then add it. */
function AddData({
  spaceId,
  sources,
  external,
  filled,
  onClose,
}: {
  spaceId: string;
  sources: Source[];
  external: DataTable[];
  filled: boolean;
  /** Hides the card again (only offered once there are tables). */
  onClose?: () => void;
}) {
  const [chosen, setChosen] = useState<Source>(sources[0] ?? "upload");
  const source = sources.includes(chosen) ? chosen : (sources[0] ?? "upload");
  return (
    <Card className="rounded-xl">
      <CardHeader
        title={filled ? "Add more data" : "Add data"}
        description={SOURCES[source].about}
        aside={
          <div className="flex items-center gap-2">
            {sources.length > 1 && (
              <SegmentedControl<Source>
                label="Where the data comes from"
                value={source}
                onChange={setChosen}
                options={sources.map((value) => ({
                  value,
                  label: SOURCES[value].label,
                  icon: SOURCES[value].icon,
                }))}
              />
            )}
            {onClose && (
              <Button size="icon" variant="ghost" aria-label="Close" onClick={onClose}>
                <X aria-hidden />
              </Button>
            )}
          </div>
        }
      />
      <div className="p-5">
        {source === "upload" && <UploadForm spaceId={spaceId} />}
        {source === "delta" && <DeltaForm spaceId={spaceId} />}
        {source === "database" && <ExternalTablesPanel spaceId={spaceId} external={external} />}
      </div>
    </Card>
  );
}

function UploadForm({ spaceId }: { spaceId: string }) {
  const limits = useDataLimits();
  const upload = useUploadTable(spaceId);
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [added, setAdded] = useState<DataTable | null>(null);
  const error = upload.error ? asApiError(upload.error) : null;
  const types = limits.data?.file_types ?? [];

  // Stop an upload that is still running when the page is left.
  useEffect(() => () => abort.current?.abort(), []);

  function choose(chosen: File | undefined) {
    if (!chosen) return;
    upload.reset();
    setAdded(null);
    const extension = chosen.name.slice(chosen.name.lastIndexOf(".")).toLowerCase();
    if (types.length && !types.includes(extension)) {
      setProblem(`${chosen.name} can't be used. Choose one of: ${types.join(", ")}.`);
      return;
    }
    if (limits.data && chosen.size > limits.data.max_upload_mb * 1024 * 1024) {
      setProblem(
        `${chosen.name} is ${fileSize(chosen.size)}; the limit is ${limits.data.max_upload_mb} MB.`,
      );
      return;
    }
    if (chosen.size === 0) {
      setProblem(`${chosen.name} is empty.`);
      return;
    }
    setProblem(null);
    setFile(chosen);
    setName("");
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (!upload.isPending) choose(event.dataTransfer.files[0]);
  }

  function clear() {
    setFile(null);
    setName("");
    if (input.current) input.current.value = "";
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    const controller = new AbortController();
    abort.current = controller;
    setProgress(0);
    upload.mutate(
      { file, name: name.trim() || undefined, onProgress: setProgress, signal: controller.signal },
      {
        onSuccess: (table) => {
          setAdded(table);
          clear();
        },
      },
    );
  }

  const uploading = upload.isPending;
  const converting = uploading && progress >= 1;
  const cancelled = upload.error?.name === "AbortError";
  const nameError =
    error?.code === "table_name" || error?.code === "table_name_taken" ? error.message : undefined;

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      {added && (
        <Notice title={`Added ${added.name}`}>
          {plural(added.row_count, "row")} and {plural(added.columns.length, "column")}, ready to
          query.
        </Notice>
      )}
      {(problem || (error && !cancelled && !nameError)) && (
        <Notice tone="error" title="File not added">
          {problem ?? error?.message}
        </Notice>
      )}

      {!file ? (
        <label
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "flex cursor-pointer flex-col items-center rounded-xl border border-dashed px-6 py-12 text-center transition-colors duration-150",
            "focus-within:ring-2 focus-within:ring-accent/30",
            dragging
              ? "border-accent bg-accent-soft"
              : "border-border-strong hover:border-accent/60 hover:bg-surface-2/50",
          )}
        >
          <span className="mb-4 flex size-12 items-center justify-center rounded-full bg-accent-soft text-accent ring-1 ring-border">
            <Upload aria-hidden className="size-5" />
          </span>
          <span className="font-medium">
            Drop a file here, or <span className="text-accent">choose one</span>
          </span>
          <span className="mt-3 flex flex-wrap justify-center gap-1.5">
            {["CSV", "TSV", "Excel", "Parquet", "JSON"].map((kind) => (
              <Badge key={kind}>{kind}</Badge>
            ))}
          </span>
          {limits.data && (
            <span className="mt-2 text-[12.5px] text-subtle">
              Up to {limits.data.max_upload_mb} MB
            </span>
          )}
          <input
            ref={input}
            type="file"
            accept={types.join(",") || undefined}
            className="sr-only"
            onChange={(event) => choose(event.target.files?.[0])}
          />
        </label>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-2/50 px-4 py-3">
            <FileUp aria-hidden className="size-4 shrink-0 text-muted" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13.5px] font-medium">{file.name}</p>
              <p className="text-[12.5px] text-subtle">
                {uploading
                  ? converting
                    ? "Uploaded. Converting to Parquet…"
                    : `Uploading… ${Math.round(progress * 100)}%`
                  : fileSize(file.size)}
              </p>
            </div>
            {!uploading && (
              <Button variant="ghost" size="icon" aria-label="Choose another file" onClick={clear}>
                <X aria-hidden />
              </Button>
            )}
          </div>
          {uploading && (
            <div
              role="progressbar"
              aria-label="Upload progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress * 100)}
              className="h-1 overflow-hidden rounded-full bg-surface-2"
            >
              <motion.div
                className={cn("h-full rounded-full bg-accent", converting && "animate-pulse")}
                animate={{ width: `${Math.max(progress, 0.02) * 100}%` }}
                transition={{ duration: 0.2, ease: "linear" }}
              />
            </div>
          )}
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-full max-w-xs">
              <TextField
                label="Table name"
                placeholder={suggestTableName(file.name)}
                value={name}
                disabled={uploading}
                onChange={(event) => setName(event.target.value)}
                hint="Leave empty to use the name shown."
                error={nameError}
              />
            </div>
            <div className="mb-6 flex gap-2">
              {uploading ? (
                <Button onClick={() => abort.current?.abort()} disabled={converting}>
                  Cancel
                </Button>
              ) : (
                <Button type="submit" variant="primary">
                  <Upload aria-hidden />
                  Upload
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </form>
  );
}

function DeltaForm({ spaceId }: { spaceId: string }) {
  const add = useAddDeltaTable(spaceId);
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [added, setAdded] = useState<DataTable | null>(null);
  const error = add.error ? asApiError(add.error) : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!path.trim()) return;
    setAdded(null);
    add.mutate(
      { path: path.trim(), name: name.trim() || undefined },
      {
        onSuccess: (table) => {
          setAdded(table);
          setPath("");
          setName("");
        },
      },
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      {added && (
        <Notice title={`Added ${added.name}`}>
          Delta version {added.delta_version ?? 0}, {plural(added.row_count, "row")}. Queries always
          read the latest version.
        </Notice>
      )}
      {error && error.code !== "validation_error" && (
        <Notice tone="error" title="Delta table not added">
          {error.message}
        </Notice>
      )}
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)]">
        <TextField
          label="Folder on the server"
          placeholder="C:\data\orders_delta"
          className="font-mono text-[13px]"
          spellCheck={false}
          value={path}
          onChange={(event) => setPath(event.target.value)}
          hint={
            <>
              The folder that contains <InlineCode>_delta_log</InlineCode>. It must be inside the
              data folder or a folder listed in <InlineCode>LOCAL_DATA_ROOTS</InlineCode>.
            </>
          }
          error={error?.fieldErrors.path}
        />
        <TextField
          label="Table name (optional)"
          placeholder={
            path.trim() ? suggestTableName(path.trim().split(/[\\/]/).pop() ?? "") : "orders"
          }
          value={name}
          onChange={(event) => setName(event.target.value)}
          error={error?.fieldErrors.name}
        />
      </div>
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={add.isPending} disabled={!path.trim()}>
          Add Delta table
        </Button>
      </div>
    </form>
  );
}

// ── Table list ───────────────────────────────────────────────────────────────

function TableRow({
  spaceId,
  table,
  editor,
}: {
  spaceId: string;
  table: DataTable;
  editor: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteTable(spaceId);
  const error = remove.error ? asApiError(remove.error) : null;
  const delta = table.source_type === "delta_path";
  const database = table.source_type === "external";

  return (
    <li>
      <div className="flex items-center gap-3 px-5 py-3.5">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="group flex min-w-0 flex-1 items-center gap-3.5 rounded-md text-left focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none"
        >
          <span
            aria-hidden
            className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted ring-1 ring-border"
          >
            {database ? (
              <DatabaseZap className="size-4" />
            ) : delta ? (
              <FolderTree className="size-4" />
            ) : (
              <FileSpreadsheet className="size-4" />
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span className="truncate font-mono text-[13.5px] font-medium">{table.name}</span>
              <Badge tone={delta || database ? "accent" : "neutral"}>
                {database ? "Database" : delta ? "Delta" : "Upload"}
              </Badge>
            </span>
            <span className="block truncate text-[12.5px] text-subtle">
              {rowsText(table.row_count, database)} · {plural(table.columns.length, "column")}
              {table.size_bytes !== null && ` · ${fileSize(table.size_bytes)}`}
              {delta && ` · version ${table.delta_version ?? 0}`} · from {table.source_ref} · added{" "}
              {timeAgo(table.created_at)}
            </span>
          </span>
          <ChevronRight
            aria-hidden
            className={cn(
              "size-4 shrink-0 text-subtle transition-transform duration-200 group-hover:text-fg",
              open && "rotate-90",
            )}
          />
        </button>
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
                onClick={() => remove.mutate(table.id)}
              >
                Remove
              </Button>
            </div>
          ) : (
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${table.name}`}
              title={
                delta ? "Remove from this space (the folder stays)" : "Remove and delete the file"
              }
              onClick={() => setConfirming(true)}
            >
              <Trash2 aria-hidden />
            </Button>
          ))}
      </div>
      {error && (
        <Notice tone="error" title="Not removed" className="mx-5 mb-3">
          {error.message}
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
            <TableDetails spaceId={spaceId} table={table} />
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

function TableDetails({ spaceId, table }: { spaceId: string; table: DataTable }) {
  const preview = usePreview(spaceId, table.id);
  return (
    <div className="space-y-4 border-t border-border bg-surface-2/30 px-5 py-4">
      <div>
        <p className="mb-2 text-[12.5px] font-medium text-muted">Columns</p>
        <ul className="flex flex-wrap gap-1.5">
          {table.columns.map((column) => (
            <li
              key={column.name}
              className="rounded-md border border-border bg-surface-2/60 px-2 py-1 font-mono text-[12px]"
            >
              {column.name} <span className="text-subtle">{column.type.toLowerCase()}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="mb-2 text-[12.5px] font-medium text-muted">
          {preview.data ? `First ${plural(preview.data.row_count, "row")}` : "First rows"}
        </p>
        {preview.isPending ? (
          <Skeleton className="h-40" />
        ) : preview.isError ? (
          <Notice tone="error" title="Could not read the table">
            {preview.error.message}
          </Notice>
        ) : (
          <ResultTable columns={preview.data.columns} rows={preview.data.rows} />
        )}
      </div>
    </div>
  );
}
