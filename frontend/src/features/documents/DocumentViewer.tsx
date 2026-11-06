import { useQuery } from "@tanstack/react-query";
import { Download, FileText, LoaderCircle, X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useId } from "react";
import { createPortal } from "react-dom";

import { Button } from "../../components/ui/Button";
import { Notice } from "../../components/ui/Notice";
import { apiBlob, asApiError } from "../../lib/api";

export interface ViewTarget {
  documentId: string;
  title: string;
  /** The page to open at (PDF only). */
  page?: number | null;
  /** The passage an answer used, shown beside the page. */
  passage?: string;
  section?: string | null;
  /** The passage was read from a picture (OCR), so it may hold mistakes. */
  ocr?: boolean;
}

interface FileInfo {
  url: string;
  filename: string;
  pdf: boolean;
  image: boolean;
}

/** The original file, fetched once with the sign-in (a plain link could not carry it). */
function useDocumentFile(documentId: string) {
  return useQuery({
    queryKey: ["document-file", documentId],
    staleTime: Infinity,
    gcTime: 10 * 60_000,
    retry: false,
    queryFn: async (): Promise<FileInfo> => {
      const { blob, filename } = await apiBlob(`/documents/${documentId}/file`);
      return {
        url: URL.createObjectURL(blob),
        filename,
        pdf: blob.type === "application/pdf",
        image: blob.type.startsWith("image/"),
      };
    },
  });
}

/**
 * A large panel showing a document at the page an answer cites, with the cited passage beside it.
 * A PDF opens in the browser's own viewer; other formats show the passage and offer the file.
 */
export function DocumentViewer({ target, onClose }: { target: ViewTarget; onClose: () => void }) {
  const titleId = useId();
  const file = useDocumentFile(target.documentId);

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

  const page = target.page ?? null;
  const showPassage = Boolean(target.passage);

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
        className="relative flex h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl border border-border bg-surface shadow-2xl sm:max-w-6xl sm:rounded-2xl"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{
          opacity: 1,
          y: 0,
          scale: 1,
          transition: { duration: 0.22, ease: [0.16, 1, 0.3, 1] },
        }}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-3.5">
          <div className="min-w-0">
            <h2 id={titleId} className="truncate text-[16px] font-semibold">
              {target.title}
            </h2>
            <p className="text-[13px] text-muted">
              {page !== null ? `Opened at page ${page}` : (target.section ?? "Whole document")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {file.data && (
              <a
                href={file.data.url}
                download={file.data.filename}
                className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg"
              >
                <Download aria-hidden className="size-3.5" />
                Download
              </a>
            )}
            <Button size="icon" variant="ghost" aria-label="Close" onClick={onClose}>
              <X aria-hidden />
            </Button>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          {showPassage && (
            <aside className="max-h-48 shrink-0 overflow-auto border-b border-border bg-surface-2/40 p-5 lg:max-h-none lg:w-80 lg:border-r lg:border-b-0">
              <p className="mb-2 text-[11px] font-semibold tracking-wide text-subtle uppercase">
                What the answer used
              </p>
              <p className="text-[13.5px] leading-relaxed whitespace-pre-wrap">{target.passage}</p>
              {target.ocr && (
                <p className="mt-3 rounded-md bg-warning-soft px-2.5 py-2 text-[12.5px] text-warning">
                  This text was read from a picture (OCR). Check the page itself for exact numbers
                  and spelling.
                </p>
              )}
            </aside>
          )}
          <div className="min-h-0 min-w-0 flex-1">
            {file.isPending ? (
              <div className="flex h-full items-center justify-center text-muted">
                <LoaderCircle aria-hidden className="size-5 animate-spin" />
                <span className="sr-only">Opening the document</span>
              </div>
            ) : file.isError ? (
              <div className="p-5">
                <Notice tone="error" title="Could not open the document">
                  {asApiError(file.error).message}
                </Notice>
              </div>
            ) : file.data.pdf ? (
              <iframe
                key={page ?? 0}
                title={target.title}
                src={`${file.data.url}#page=${page ?? 1}&view=FitH`}
                className="size-full border-0 bg-white"
              />
            ) : file.data.image ? (
              <div className="flex size-full items-center justify-center overflow-auto bg-surface-2/40 p-4">
                <img
                  src={file.data.url}
                  alt={target.title}
                  className="max-h-full max-w-full object-contain"
                />
              </div>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
                <FileText aria-hidden className="size-9 text-subtle" />
                <p className="max-w-sm text-[14px] text-muted">
                  This kind of file opens in its own app. The passage the answer used is shown
                  beside it; download the file to read all of it.
                </p>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </div>,
    document.body,
  );
}
