import { LayoutDashboard, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { BareInput } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { plural, timeAgo } from "../../lib/format";
import { KeptModal, KeptPreview } from "./KeptView";
import { SpaceTabs } from "./SpaceTabs";
import {
  useCreateDashboard,
  useDashboards,
  useDeleteDashboard,
  useDeleteItem,
  useRefreshDashboard,
  useRefreshItem,
  useRenameDashboard,
  useRenameItem,
} from "./queries";
import type { Dashboard, KeptItem } from "./types";

/**
 * A person's kept answers. Each tile shows the result as of its last refresh, and Refresh runs
 * its SQL again: no need to ask the question once more.
 */
export function DashboardsPage() {
  const { spaceId = "" } = useParams();
  const dashboards = useDashboards(spaceId);
  const refreshAll = useRefreshDashboard(spaceId);
  const [chosen, setChosen] = useState<string | null>(null);
  const list = dashboards.data ?? [];
  const current = list.find((d) => d.id === chosen) ?? list[0];

  return (
    <SpaceTabs
      spaceId={spaceId}
      section="dashboards"
      title="Dashboards"
      description="Answers you kept from a chat. Refresh them to see today's numbers without asking again. Only you can see your dashboards."
      actions={
        current && (
          <Button
            loading={refreshAll.isPending}
            disabled={current.items.length === 0}
            onClick={() => refreshAll.mutate(current.id)}
          >
            <RefreshCw aria-hidden />
            Refresh all
          </Button>
        )
      }
    >
      {dashboards.isPending ? (
        <Skeleton className="h-48" />
      ) : dashboards.isError ? (
        <Notice tone="error" title="Could not load your dashboards">
          {dashboards.error.message}
        </Notice>
      ) : (
        <div className="space-y-5">
          <Boards spaceId={spaceId} list={list} current={current} onChoose={setChosen} />
          {refreshAll.error && (
            <Notice tone="error" title="Could not refresh">
              {asApiError(refreshAll.error).message}
            </Notice>
          )}
          {!current || current.items.length === 0 ? (
            <Card>
              <EmptyState icon={LayoutDashboard} title="Nothing kept yet">
                Ask a question in a chat, then use <b>Keep</b> on the answer to put it here.{" "}
                <Link to="/chat" className="text-accent underline-offset-2 hover:underline">
                  Go to the chat
                </Link>
              </EmptyState>
            </Card>
          ) : (
            <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
              {current.items.map((item) => (
                <Tile key={item.id} spaceId={spaceId} item={item} />
              ))}
            </div>
          )}
        </div>
      )}
    </SpaceTabs>
  );
}

// ── The boards ───────────────────────────────────────────────────────────────

function Boards({
  spaceId,
  list,
  current,
  onChoose,
}: {
  spaceId: string;
  list: Dashboard[];
  current: Dashboard | undefined;
  onChoose: (id: string) => void;
}) {
  const create = useCreateDashboard(spaceId);
  const rename = useRenameDashboard(spaceId);
  const remove = useDeleteDashboard(spaceId);
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [name, setName] = useState("");
  const error = create.error ?? rename.error ?? remove.error;

  function submit(event: FormEvent) {
    event.preventDefault();
    const text = name.trim();
    if (!text) return;
    if (renaming && current) {
      rename.mutate({ id: current.id, name: text }, { onSuccess: () => setRenaming(false) });
    } else {
      create.mutate(text, {
        onSuccess: (made) => {
          setAdding(false);
          setName("");
          onChoose(made.id);
        },
      });
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {list.map((board) => (
          <button
            key={board.id}
            type="button"
            aria-pressed={board.id === current?.id}
            onClick={() => onChoose(board.id)}
            className={cn(
              "rounded-full border px-3 py-1 text-[13px] transition-colors",
              board.id === current?.id
                ? "border-accent/50 bg-accent-soft text-fg"
                : "border-border text-muted hover:bg-surface-2/60 hover:text-fg",
            )}
          >
            {board.name}
          </button>
        ))}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setAdding(true);
            setRenaming(false);
            setName("");
          }}
        >
          <Plus aria-hidden className="size-3.5" />
          New dashboard
        </Button>
        {current && !confirming && (
          <span className="ml-auto flex gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setRenaming(true);
                setAdding(false);
                setName(current.name);
              }}
            >
              <Pencil aria-hidden className="size-3.5" />
              Rename
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-danger"
              onClick={() => setConfirming(true)}
            >
              <Trash2 aria-hidden className="size-3.5" />
              Delete
            </Button>
          </span>
        )}
        {current && confirming && (
          <span className="ml-auto flex items-center gap-1 text-[13px]">
            Delete “{current.name}” and its {plural(current.items.length, "answer")}?
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Keep
            </Button>
            <Button
              size="sm"
              className="text-danger"
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(current.id, {
                  onSuccess: () => {
                    setConfirming(false);
                    onChoose("");
                  },
                })
              }
            >
              Delete
            </Button>
          </span>
        )}
      </div>
      {(adding || renaming) && (
        <form onSubmit={submit} className="flex max-w-md items-center gap-2">
          <BareInput
            aria-label="Dashboard name"
            autoFocus
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Dashboard name"
          />
          <Button
            type="submit"
            variant="primary"
            loading={create.isPending || rename.isPending}
            disabled={!name.trim()}
          >
            {renaming ? "Save" : "Create"}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setAdding(false);
              setRenaming(false);
            }}
          >
            Cancel
          </Button>
        </form>
      )}
      {error && (
        <Notice tone="error" title="That didn't work">
          {asApiError(error).message}
        </Notice>
      )}
    </div>
  );
}

// ── One kept answer ──────────────────────────────────────────────────────────

function Tile({ spaceId, item }: { spaceId: string; item: KeptItem }) {
  const refresh = useRefreshItem(spaceId);
  const rename = useRenameItem(spaceId);
  const remove = useDeleteItem(spaceId);
  const [title, setTitle] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const columns = item.columns ?? [];
  const rows = item.rows ?? [];
  const problem = refresh.error ?? rename.error ?? remove.error;

  return (
    <Card className="flex flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0 flex-1">
          {title === null ? (
            <h2 className="truncate text-[14.5px] font-semibold" title={item.question}>
              {item.title}
            </h2>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const text = title.trim();
                if (text) rename.mutate({ id: item.id, title: text });
                setTitle(null);
              }}
            >
              <BareInput
                aria-label="Title"
                autoFocus
                maxLength={200}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                onBlur={() => setTitle(null)}
              />
            </form>
          )}
          <p className="text-[12.5px] text-subtle">
            {item.refreshed_at ? `Updated ${timeAgo(item.refreshed_at)}` : "Not refreshed yet"}
            {item.row_count !== null && ` · ${plural(item.row_count, "row")}`}
          </p>
        </div>
        <div className="flex shrink-0 gap-0.5">
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Refresh ${item.title}`}
            title="Run this again"
            loading={refresh.isPending}
            onClick={() => refresh.mutate(item.id)}
          >
            <RefreshCw aria-hidden className="size-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Rename ${item.title}`}
            title="Rename"
            onClick={() => setTitle(item.title)}
          >
            <Pencil aria-hidden className="size-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Remove ${item.title}`}
            title="Remove from this dashboard"
            loading={remove.isPending}
            onClick={() => remove.mutate(item.id)}
          >
            <Trash2 aria-hidden className="size-3.5" />
          </Button>
        </div>
      </div>
      <div className="min-w-0 flex-1 space-y-3 p-4">
        {(item.refresh_error || problem) && (
          <Notice tone="warn" title="Could not refresh this one">
            {item.refresh_error || asApiError(problem).message} The result below is from the last
            time it worked.
          </Notice>
        )}
        {columns.length === 0 && rows.length === 0 ? (
          <p className="text-[13px] text-muted">The query returned no rows.</p>
        ) : (
          <KeptPreview item={item} onOpen={() => setOpen(true)} />
        )}
      </div>
      {open && (
        <KeptModal
          item={item}
          refreshing={refresh.isPending}
          onRefresh={() => refresh.mutate(item.id)}
          onClose={() => setOpen(false)}
        />
      )}
    </Card>
  );
}
