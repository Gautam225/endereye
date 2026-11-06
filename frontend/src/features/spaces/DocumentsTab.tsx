import {
  Check,
  Eye,
  FileText,
  FileUp,
  Pencil,
  RefreshCw,
  ScanText,
  Search,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { useRef, useState, type DragEvent, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { BareInput } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { fileSize, plural, timeAgo } from "../../lib/format";
import { useUnloadWarning } from "../../lib/useUnloadWarning";
import { DocumentViewer, type ViewTarget } from "../documents/DocumentViewer";
import {
  useDeleteDocument,
  useDocumentLimits,
  useDocuments,
  useRenameDocument,
  useRereadDocument,
  useUploadDocument,
} from "./queries";
import { needsReread, pagesText } from "./library";
import type { DocumentInfo, Space } from "./types";

/**
 * The files a space answers from. Everyone in the space can open them (an answer's page
 * citations lead here); editors add, rename, read again and remove.
 */
export function DocumentsTab({ space }: { space: Space }) {
  const editor = space.my_role === "editor";
  const documents = useDocuments(space.id);
  const [query, setQuery] = useState("");
  const [viewing, setViewing] = useState<ViewTarget | null>(null);
  const reread = useRereadDocument(space.id);

  const all = documents.data ?? [];
  const needle = query.trim().toLowerCase();
  const shown = all.filter(
    (d) =>
      !needle ||
      d.title.toLowerCase().includes(needle) ||
      d.filename.toLowerCase().includes(needle),
  );
  const outdated = all.filter(needsReread);

  return (
    <div className="space-y-6">
      {editor && <Uploader spaceId={space.id} />}

      {outdated.length > 0 && editor && (
        <Notice
          tone="warn"
          title={`${plural(outdated.length, "document")} can show page numbers after a re-read`}
          action={
            <Button
              size="sm"
              loading={reread.isPending}
              onClick={() => {
                for (const document of outdated) reread.mutate(document.id);
              }}
            >
              <RefreshCw aria-hidden />
              Read again
            </Button>
          }
        >
          They were added before answers could cite pages. Reading them again takes a moment and
          changes nothing else.
        </Notice>
      )}

      <Card className="overflow-hidden">
        <CardHeader
          title="Document library"
          description={
            all.length > 0
              ? `${plural(all.length, "document")} in this space. Answers quote them and point to the page.`
              : "Policies, contracts, reports and notes that answers can quote."
          }
        />
        {all.length > 6 && (
          <div className="border-b border-border px-5 py-3">
            <label className="relative block max-w-sm">
              <span className="sr-only">Search documents</span>
              <Search
                aria-hidden
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle"
              />
              <input
                type="search"
                placeholder="Search by name"
                maxLength={100}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-9 w-full rounded-lg border border-border bg-bg pr-3 pl-9 text-[14px] placeholder:text-subtle hover:border-border-strong focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
              />
            </label>
          </div>
        )}
        {documents.isPending ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : documents.isError ? (
          <Notice tone="error" title="Could not load the documents" className="m-5">
            {documents.error.message}
          </Notice>
        ) : all.length === 0 ? (
          <EmptyState icon={FileText} title="No documents yet">
            {editor
              ? "Add a PDF, Word, PowerPoint, Excel, HTML, Markdown, text or image file above."
              : "Editors of this space can add documents."}
          </EmptyState>
        ) : shown.length === 0 ? (
          <p className="px-5 py-10 text-center text-[13.5px] text-muted">
            Nothing matches that search.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {shown.map((document) => (
              <Row
                key={document.id}
                spaceId={space.id}
                document={document}
                editor={editor}
                onView={() =>
                  setViewing({ documentId: document.id, title: document.title, page: 1 })
                }
              />
            ))}
          </ul>
        )}
      </Card>

      {viewing && <DocumentViewer target={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

// ── Adding files ─────────────────────────────────────────────────────────────

function Uploader({ spaceId }: { spaceId: string }) {
  const limits = useDocumentLimits(spaceId);
  const upload = useUploadDocument(spaceId);
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [over, setOver] = useState(false);
  const [now, setNow] = useState<{ name: string; index: number; of: number } | null>(null);
  const [progress, setProgress] = useState(0);
  const [problems, setProblems] = useState<string[]>([]);
  useUnloadWarning(now !== null);

  function check(file: File): string | null {
    const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    const types = limits.data?.file_types ?? [];
    if (types.length && !types.includes(extension)) {
      return `${file.name} can't be used. Choose one of: ${types.join(", ")}.`;
    }
    if (limits.data && file.size > limits.data.max_upload_mb * 1024 * 1024) {
      return `${file.name} is ${fileSize(file.size)}; the limit is ${limits.data.max_upload_mb} MB.`;
    }
    return null;
  }

  async function add(files: File[]) {
    if (files.length === 0 || now) return;
    const found: string[] = [];
    const good = files.filter((file) => {
      const problem = check(file);
      if (problem) found.push(problem);
      return !problem;
    });
    for (const [index, file] of good.entries()) {
      const controller = new AbortController();
      abort.current = controller;
      setNow({ name: file.name, index: index + 1, of: good.length });
      setProgress(0);
      try {
        await upload.mutateAsync({ file, onProgress: setProgress, signal: controller.signal });
      } catch (error) {
        found.push(`${file.name}: ${asApiError(error).message}`);
      }
    }
    setNow(null);
    setProblems(found);
    if (input.current) input.current.value = "";
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setOver(false);
    void add([...event.dataTransfer.files]);
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cn(
          "flex flex-col items-center gap-3 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors",
          over ? "border-accent bg-accent-soft" : "border-border bg-surface/50",
        )}
      >
        <span className="flex size-11 items-center justify-center rounded-full bg-surface-2 text-accent">
          <UploadCloud aria-hidden className="size-5" />
        </span>
        <div>
          <p className="font-medium">
            {now
              ? `Reading ${now.name}${now.of > 1 ? ` (${now.index} of ${now.of})` : ""}… ${Math.round(progress * 100)}%`
              : "Drop files here to add them"}
          </p>
          <p className="text-[13px] text-muted">
            {limits.data
              ? `PDF, Word, PowerPoint, Excel, HTML, Markdown, text or image, up to ${limits.data.max_upload_mb} MB each. Scans and pictures are read with OCR.`
              : "PDF, Word, PowerPoint, Excel, HTML, Markdown, text or image. Scans are read with OCR."}
          </p>
        </div>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={limits.data?.file_types.join(",")}
          onChange={(event) => void add([...(event.target.files ?? [])])}
        />
        <Button loading={now !== null} onClick={() => input.current?.click()}>
          <FileUp aria-hidden />
          Choose files
        </Button>
      </div>
      {problems.length > 0 && (
        <Notice
          tone="error"
          title={problems.length === 1 ? "A file was not added" : "Some files were not added"}
        >
          <ul className="space-y-0.5">
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </Notice>
      )}
    </div>
  );
}

const capitalised = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const pageWord = (pages: number[]) => (pages.length === 1 ? "That page is" : "Those pages are");

// ── One document ─────────────────────────────────────────────────────────────

function Row({
  spaceId,
  document,
  editor,
  onView,
}: {
  spaceId: string;
  document: DocumentInfo;
  editor: boolean;
  onView: () => void;
}) {
  const rename = useRenameDocument(spaceId);
  const reread = useRereadDocument(spaceId);
  const remove = useDeleteDocument(spaceId);
  const [title, setTitle] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const failed = document.status === "failed";
  const reading = document.status === "processing";
  const problem = rename.error ?? reread.error ?? remove.error;

  function save(event: FormEvent) {
    event.preventDefault();
    const text = (title ?? "").trim();
    if (text && text !== document.title) rename.mutate({ id: document.id, title: text });
    setTitle(null);
  }

  return (
    <li className="space-y-2 px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <span
          aria-hidden
          className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-[11px] font-semibold text-muted uppercase"
        >
          {document.filename.split(".").pop()?.slice(0, 4)}
        </span>
        <div className="min-w-0 flex-1">
          {title === null ? (
            <p className="flex flex-wrap items-center gap-2">
              <span className="truncate font-medium">{document.title}</span>
              <Badge tone={failed ? "error" : reading ? "neutral" : "ok"}>
                {failed ? "Could not be read" : reading ? "Reading…" : "Ready"}
              </Badge>
            </p>
          ) : (
            <form onSubmit={save} className="flex max-w-md items-center gap-1.5">
              <BareInput
                aria-label="Document title"
                autoFocus
                maxLength={255}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                onKeyDown={(event) => event.key === "Escape" && setTitle(null)}
              />
              <Button type="submit" size="icon" variant="primary" aria-label="Save the title">
                <Check aria-hidden />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                aria-label="Cancel"
                onClick={() => setTitle(null)}
              >
                <X aria-hidden />
              </Button>
            </form>
          )}
          <p className="truncate text-[12.5px] text-subtle">
            {document.filename} · {fileSize(document.size_bytes)}
            {document.page_count !== null && ` · ${plural(document.page_count, "page")}`}
            {" · added "}
            {timeAgo(document.created_at)}
            {document.uploaded_by && ` by ${document.uploaded_by}`}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {document.status === "ready" && (
            <Button size="sm" variant="ghost" onClick={onView}>
              <Eye aria-hidden />
              View
            </Button>
          )}
          {editor &&
            (confirming ? (
              <>
                <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                  Keep
                </Button>
                <Button
                  size="sm"
                  className="text-danger hover:bg-danger-soft"
                  loading={remove.isPending}
                  onClick={() => remove.mutate(document.id)}
                >
                  Remove
                </Button>
              </>
            ) : (
              <>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={`Rename ${document.title}`}
                  title="Rename"
                  disabled={reading}
                  onClick={() => setTitle(document.title)}
                >
                  <Pencil aria-hidden />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={`Read ${document.title} again`}
                  title="Read again"
                  disabled={reading}
                  loading={reread.isPending}
                  onClick={() => reread.mutate(document.id)}
                >
                  <RefreshCw aria-hidden />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={`Remove ${document.title}`}
                  title="Remove"
                  onClick={() => setConfirming(true)}
                >
                  <Trash2 aria-hidden />
                </Button>
              </>
            ))}
        </div>
      </div>
      {failed && document.error && (
        <Notice tone="warn" title="Why it could not be read">
          {document.error}
        </Notice>
      )}
      {document.unread_pages.length > 0 && (
        <Notice
          tone="warn"
          title={`${capitalised(pagesText(document.unread_pages))} could not be read`}
          action={
            editor ? (
              <Button
                size="sm"
                loading={reread.isPending}
                disabled={reading}
                onClick={() => reread.mutate(document.id)}
              >
                <RefreshCw aria-hidden />
                Read again
              </Button>
            ) : undefined
          }
        >
          {pageWord(document.unread_pages)} a picture with no text that could be read, so answers
          cannot use {document.unread_pages.length === 1 ? "it" : "them"}. Ask an administrator to
          turn on OCR (DOCUMENT_OCR) or raise its page limit, then read the document again.
        </Notice>
      )}
      {document.ocr_pages.length > 0 && (
        <p className="flex items-start gap-2 text-[12.5px] text-subtle">
          <ScanText aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          <span>
            {capitalised(pagesText(document.ocr_pages))}{" "}
            {document.ocr_pages.length === 1 ? "was" : "were"} read from a picture (OCR). Numbers
            and spelling there can contain mistakes: check the original page when it matters.
          </span>
        </p>
      )}
      {problem && (
        <Notice tone="error" title="That did not work">
          {asApiError(problem).message}
        </Notice>
      )}
    </li>
  );
}
