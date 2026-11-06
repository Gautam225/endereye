import { LoaderCircle, Search, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "../../components/ui/Button";
import { Skeleton } from "../../components/ui/Skeleton";
import { cn } from "../../lib/cn";
import { plural } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import { useKeptItems } from "./queries";
import type { KeptSummary } from "./types";

/**
 * A large panel for choosing kept answers: a search box on top, the matches below (loaded a page
 * at a time, so thousands are fine), and Done at the bottom right. Nothing changes until Done.
 */
export function AnswersPicker({
  spaceId,
  initial,
  max,
  onDone,
  onClose,
}: {
  spaceId: string;
  /** What is already chosen, so it shows ticked and can be changed. */
  initial: KeptSummary[];
  max: number;
  onDone: (chosen: KeptSummary[]) => void;
  onClose: () => void;
}) {
  const titleId = useId();
  const searchBox = useRef<HTMLInputElement>(null);
  const sentinel = useRef<HTMLDivElement>(null);
  const [text, setText] = useState("");
  const search = useDebounced(text, 250);
  // The draft is a map so a ticked answer stays ticked while the search changes underneath it.
  const [draft, setDraft] = useState(() => new Map(initial.map((item) => [item.id, item])));
  const results = useKeptItems(spaceId, search);
  const rows = results.data?.pages.flatMap((page) => page.items) ?? [];
  const total = results.data?.pages[0]?.total ?? 0;
  const full = draft.size >= max;

  useEffect(() => {
    searchBox.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  // Scrolling to the end of the list loads the next page.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = results;
  useEffect(() => {
    const element = sentinel.current;
    if (!element || !hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting) && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: "120px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, rows.length]);

  function toggle(item: KeptSummary) {
    setDraft((now) => {
      const next = new Map(now);
      if (next.has(item.id)) next.delete(item.id);
      else if (next.size < max) next.set(item.id, item);
      return next;
    });
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6">
      <div aria-hidden className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl border border-border bg-surface shadow-2xl sm:h-[42rem] sm:max-w-3xl sm:rounded-2xl"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div>
            <h2 id={titleId} className="text-[16px] font-semibold">
              Choose answers
            </h2>
            <p className="text-[13px] text-muted">
              Search your kept answers and tick the ones this report should hold. Up to {max}.
            </p>
          </div>
          <Button size="icon" variant="ghost" aria-label="Close" onClick={onClose}>
            <X aria-hidden />
          </Button>
        </div>

        <div className="border-b border-border px-5 py-3">
          <label className="flex h-10 items-center gap-2 rounded-md border border-border bg-surface-2/60 px-3 focus-within:ring-2 focus-within:ring-accent/40">
            <Search aria-hidden className="size-4 shrink-0 text-subtle" />
            <input
              ref={searchBox}
              value={text}
              onChange={(event) => setText(event.target.value)}
              aria-label="Search kept answers"
              placeholder="Search by title or question"
              className="h-full w-full bg-transparent text-[14px] outline-none placeholder:text-subtle"
            />
            {results.isFetching && !isFetchingNextPage && (
              <LoaderCircle aria-hidden className="size-4 shrink-0 animate-spin text-subtle" />
            )}
          </label>
          <p aria-live="polite" className="mt-2 text-[12.5px] text-subtle">
            {results.isPending
              ? "Loading…"
              : search.trim()
                ? `${plural(total, "answer")} match “${search.trim()}”`
                : `${plural(total, "kept answer")}`}
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {results.isPending ? (
            <div className="space-y-2 p-5">
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
            </div>
          ) : results.isError ? (
            <p className="p-8 text-center text-[13px] text-danger">{results.error.message}</p>
          ) : rows.length === 0 ? (
            <p className="px-6 py-16 text-center text-[13.5px] text-muted">
              {search.trim()
                ? "Nothing matches that search. Try fewer or different words."
                : "You have not kept any answers yet. Use Keep on an answer in a chat first."}
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {rows.map((item) => {
                const on = draft.has(item.id);
                const blocked = full && !on;
                return (
                  <li key={item.id}>
                    <label
                      className={cn(
                        "flex items-start gap-3 px-5 py-3 transition-colors",
                        blocked ? "cursor-not-allowed opacity-50" : "cursor-pointer",
                        on ? "bg-accent-soft/60" : !blocked && "hover:bg-surface-2/50",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={on}
                        disabled={blocked}
                        onChange={() => toggle(item)}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-medium">{item.title}</span>
                        {item.title !== item.question && (
                          <span className="block truncate text-[12.5px] text-muted">
                            {item.question}
                          </span>
                        )}
                      </span>
                      <span className="hidden shrink-0 rounded-md bg-surface-2 px-2 py-0.5 text-[11.5px] text-subtle sm:block">
                        {item.dashboard_name}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          {hasNextPage && (
            <div ref={sentinel} className="flex justify-center p-4">
              {isFetchingNextPage ? (
                <LoaderCircle aria-hidden className="size-4 animate-spin text-subtle" />
              ) : (
                <Button size="sm" variant="ghost" onClick={() => void fetchNextPage()}>
                  Load more
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-border bg-surface-2/40 px-5 py-3.5">
          <p className="min-w-0 flex-1 text-[13px] text-muted">
            <b className="font-semibold text-fg">{draft.size}</b> of {max} selected
            {full && " · the most a report can hold"}
            {draft.size > 0 && (
              <button
                type="button"
                className="ml-3 text-accent underline-offset-2 hover:underline"
                onClick={() => setDraft(new Map())}
              >
                Clear all
              </button>
            )}
          </p>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => onDone([...draft.values()])}>
              {draft.size > 0 ? `Add ${draft.size}` : "Done"}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
