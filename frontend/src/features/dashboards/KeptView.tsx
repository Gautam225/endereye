import { Maximize2, RefreshCw, X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "../../components/ui/Button";
import { plural, timeAgo } from "../../lib/format";
import { panelsOf } from "../chat/chart";
import { ResultChart, TotalsTiles } from "../chat/ResultChart";
import { ResultTable } from "../spaces/ResultTable";
import type { KeptItem } from "./types";

const PREVIEW_WIDTH = 720; // the width a preview is drawn at before it is shrunk to fit

/** What a kept answer shows: its chart(s), or the table when it has no chart. */
export function KeptBody({ item, preview = false }: { item: KeptItem; preview?: boolean }) {
  // A preview is a picture to look at: no download button and no title (the card has both).
  const quiet = useRef<HTMLDivElement>(null);
  const columns = item.columns ?? [];
  const rows = item.rows ?? [];
  const panels = item.chart ? panelsOf(item.chart, columns, rows) : [];

  if (panels.length > 0) {
    return (
      <div className="space-y-4">
        {(item.chart?.totals?.length ?? 0) > 0 && <TotalsTiles totals={item.chart?.totals ?? []} />}
        {panels.map((panel) => (
          <ResultChart
            key={panel.key}
            spec={preview ? { ...panel.spec, title: "" } : panel.spec}
            columns={columns}
            rows={panel.rows}
            name={item.title}
            holderRef={preview ? quiet : undefined}
          />
        ))}
      </div>
    );
  }
  if (rows.length > 0) {
    return (
      <ResultTable
        columns={columns}
        rows={rows}
        className={preview ? undefined : "max-h-[60dvh]"}
      />
    );
  }
  return <p className="text-[13px] text-muted">The query returned no rows.</p>;
}

/**
 * The small version of a kept answer shown on the dashboard: the real chart, shrunk, that cannot
 * be touched. Clicking it opens the full, interactive one.
 */
export function KeptPreview({ item, onOpen }: { item: KeptItem; onOpen: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);

  // Draw the answer at a normal width, then shrink it to fit the box whole, whatever its shape,
  // and centre it: a short chart is not left with an empty strip under it.
  useEffect(() => {
    const outer = box.current;
    const inner = content.current;
    if (!outer || !inner) return;
    const fit = () => {
      const { clientWidth: w, clientHeight: h } = outer;
      const { offsetWidth: cw, offsetHeight: ch } = inner;
      if (cw && ch) setScale(Math.min(w / cw, h / ch, 1));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(outer);
    observer.observe(inner);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={box}
      className="group relative h-48 overflow-hidden rounded-md border border-border bg-surface-2/30"
    >
      <div
        ref={content}
        inert
        style={{
          width: PREVIEW_WIDTH,
          transform: `translate(-50%, -50%) scale(${scale})`,
          opacity: scale ? 1 : 0,
        }}
        className="pointer-events-none absolute top-1/2 left-1/2 p-4 select-none"
      >
        <KeptBody item={item} preview />
      </div>
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Open ${item.title} larger`}
        className="absolute inset-0 cursor-zoom-in transition-colors hover:bg-surface-2/30 focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:outline-none focus-visible:ring-inset"
      >
        <span className="absolute top-2 right-2 flex items-center gap-1.5 rounded-md border border-border bg-surface/90 px-2 py-1 text-[12px] font-medium text-muted opacity-0 shadow-sm transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
          <Maximize2 aria-hidden className="size-3" />
          Open
        </span>
      </button>
    </div>
  );
}

/** A kept answer in a large panel, where the chart can be hovered, filtered and downloaded. */
export function KeptModal({
  item,
  refreshing,
  onRefresh,
  onClose,
}: {
  item: KeptItem;
  refreshing: boolean;
  onRefresh: () => void;
  onClose: () => void;
}) {
  const titleId = useId();

  useEffect(() => {
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

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6">
      <motion.div
        aria-hidden
        className="absolute inset-0 bg-black/55"
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1, transition: { duration: 0.18 } }}
      />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl border border-border bg-surface shadow-2xl sm:max-w-5xl sm:rounded-2xl"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{
          opacity: 1,
          y: 0,
          scale: 1,
          transition: { duration: 0.22, ease: [0.16, 1, 0.3, 1] },
        }}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="truncate text-[16px] font-semibold">
              {item.title}
            </h2>
            <p className="truncate text-[13px] text-muted" title={item.question}>
              {item.refreshed_at ? `Updated ${timeAgo(item.refreshed_at)}` : "Not refreshed yet"}
              {item.row_count !== null && ` · ${plural(item.row_count, "row")}`}
              {item.question && ` · ${item.question}`}
            </p>
          </div>
          <div className="flex shrink-0 gap-1">
            <Button size="sm" variant="ghost" loading={refreshing} onClick={onRefresh}>
              <RefreshCw aria-hidden className="size-3.5" />
              Refresh
            </Button>
            <Button size="icon" variant="ghost" aria-label="Close" onClick={onClose}>
              <X aria-hidden />
            </Button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-5">
          <KeptBody item={item} />
        </div>
      </motion.div>
    </div>,
    document.body,
  );
}
