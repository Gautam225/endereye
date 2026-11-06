import { FileText, ScanText } from "lucide-react";

import { cn } from "../../lib/cn";
import { chipText, where } from "./citations";
import type { Citation } from "./types";

/** Shown right after the sentence it supports: the document and page, and a click opens it. */
export function CitationChip({
  citation,
  onOpen,
}: {
  citation: Citation;
  onOpen: (citation: Citation) => void;
}) {
  const openable = citation.document_id !== null;
  return (
    <button
      type="button"
      disabled={!openable}
      onClick={() => onOpen(citation)}
      title={`${citation.ocr ? "Read from a scan (may contain mistakes). " : ""}${citation.text.slice(0, 280)}${citation.text.length > 280 ? "…" : ""}`}
      aria-label={`Source ${citation.tag.slice(1)}: ${where(citation)}`}
      className={cn(
        "mx-1 inline-flex max-w-[16rem] -translate-y-[0.05em] items-center gap-1 rounded-md border px-1.5 py-0.5 align-baseline text-[12px] leading-none font-medium transition-colors",
        openable
          ? "border-accent/40 bg-accent-soft text-accent hover:border-accent hover:bg-accent hover:text-accent-fg"
          : "border-border bg-surface-2 text-subtle",
      )}
    >
      {citation.ocr ? (
        <ScanText aria-hidden className="size-3 shrink-0" />
      ) : (
        <FileText aria-hidden className="size-3 shrink-0" />
      )}
      <span className="truncate">{chipText(citation)}</span>
    </button>
  );
}

/**
 * The answer's sentences already carry a small button for each passage they rest on, and a click
 * opens the page. So nothing more is listed under the answer, except when the AI cited nothing:
 * then the passages it was given are offered as the same small buttons, in one quiet row.
 */
export function CitationList({
  citations,
  onOpen,
}: {
  citations: Citation[];
  onOpen: (citation: Citation) => void;
}) {
  if (citations.length === 0 || citations.some((c) => c.cited)) return null;
  return (
    <section
      data-no-print
      aria-label="Passages found"
      className="flex flex-wrap items-center gap-x-1 gap-y-1.5 text-[12.5px] text-subtle"
    >
      <span>Passages found:</span>
      {citations.map((citation) => (
        <CitationChip key={citation.tag} citation={citation} onOpen={onOpen} />
      ))}
    </section>
  );
}
