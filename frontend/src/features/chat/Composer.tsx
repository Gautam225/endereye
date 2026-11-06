import {
  ArrowUp,
  AtSign,
  CircleAlert,
  Database,
  FileText,
  LoaderCircle,
  Paperclip,
  Square,
  X,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import {
  activeMention,
  filterMentionables,
  insertMention,
  splitMentions,
  type Mentionable,
} from "./mentions";

const MAX_LENGTH = 2000;
/** What can be attached: the same kinds of files a space can hold as documents. */
export const ATTACH_TYPES =
  ".pdf,.docx,.pptx,.xlsx,.html,.htm,.md,.markdown,.txt,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp";

/** A file attached to this conversation, shown as a chip above the question box. */
export interface Attachment {
  key: string;
  filename: string;
  status: "uploading" | "ready" | "failed";
  /** Why it failed. */
  error?: string;
  /** Set once the server has it; used to remove it. */
  id?: string;
}

/** Everything the question box needs for files and @mentions. */
export interface ComposerFiles {
  /** Documents that @ can point at (this chat's files and the space's). */
  documents: Mentionable[];
  attachments: Attachment[];
  onAttach: (files: File[]) => void;
  onRemove: (attachment: Attachment) => void;
}

/**
 * The question box. Enter sends, Shift+Enter starts a new line, the paperclip (or dropping a
 * file) attaches documents to this conversation, and typing @ offers the documents to point at.
 * While an answer is being written the send button becomes Stop.
 */
export function Composer({
  onSend,
  running,
  onStop,
  placeholder,
  autoFocus = false,
  initialText = "",
  toolbar,
  trailing,
  files,
  className,
}: {
  onSend: (text: string) => void;
  running: boolean;
  onStop: () => void;
  placeholder: string;
  autoFocus?: boolean;
  initialText?: string;
  /** Extra controls to the left of the send button (for example the Ask / Search switch). */
  toolbar?: ReactNode;
  /** Controls just before the send button (for example how to answer). */
  trailing?: ReactNode;
  files?: ComposerFiles;
  className?: string;
}) {
  const [text, setText] = useState(initialText);
  const [caret, setCaret] = useState(initialText.length);
  const [choice, setChoice] = useState(0);
  const [dismissed, setDismissed] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  // Where the list of things to mention opens: toward the side of the box with more room.
  const [place, setPlace] = useState<{ up: boolean; room: number }>({ up: true, room: 288 });
  const empty = text.trim() === "";

  const active = files ? activeMention(text, caret) : null;
  const options =
    active && files && dismissed !== active.start
      ? filterMentionables(files.documents, active.query)
      : [];
  const picking = options.length > 0;

  // Grow with the text, up to about eight lines.
  useEffect(() => {
    const element = area.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`;
  }, [text]);

  useEffect(() => {
    if (autoFocus) area.current?.focus();
  }, [autoFocus]);

  function measure() {
    const box = form.current?.getBoundingClientRect();
    if (!box) return;
    const above = box.top - 76; // the page header is above
    const below = window.innerHeight - box.bottom - 16;
    setPlace({ up: above >= below, room: Math.max(176, Math.min(352, Math.max(above, below))) });
  }

  function send() {
    if (empty || running) return;
    onSend(text.trim());
    setText("");
    setCaret(0);
  }

  function choose(document: Mentionable) {
    if (!active) return;
    const next = insertMention(text, caret, active, document.mention);
    setText(next.text);
    setCaret(next.caret);
    setChoice(0);
    // Put the cursor after the inserted name once React has updated the text.
    requestAnimationFrame(() => {
      area.current?.focus();
      area.current?.setSelectionRange(next.caret, next.caret);
    });
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (picking) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setChoice((current) => (current + step + options.length) % options.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        const picked = options[choice] ?? options[0];
        if (picked) choose(picked);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setDismissed(active?.start ?? null);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (running) onStop();
    else send();
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (files && event.dataTransfer.files.length > 0) files.onAttach([...event.dataTransfer.files]);
  }

  return (
    <form
      ref={form}
      onSubmit={submit}
      onDragOver={(event) => {
        if (files) {
          event.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cn(
        "relative rounded-2xl border bg-surface p-3 shadow-[0_1px_2px_rgb(0_0_0/0.04),0_8px_24px_-12px_rgb(0_0_0/0.18)] transition-[border-color,box-shadow]",
        dragging
          ? "border-accent ring-4 ring-accent/15"
          : "border-border-strong/70 focus-within:border-border-strong focus-within:ring-4 focus-within:ring-accent/10",
        className,
      )}
    >
      {picking && (
        <ul
          role="listbox"
          aria-label="Tables and documents you can mention"
          style={{ maxHeight: place.room }}
          className={cn(
            "absolute left-3 z-20 w-80 max-w-[calc(100%-1.5rem)] overflow-y-auto overscroll-contain rounded-xl border border-border bg-surface p-1 shadow-lg",
            place.up ? "bottom-full mb-2" : "top-full mt-2",
          )}
        >
          {options.map((document, index) => (
            <li
              key={document.id}
              role="option"
              aria-selected={index === choice}
              ref={(element) => {
                if (index === choice) element?.scrollIntoView({ block: "nearest" });
              }}
            >
              <button
                type="button"
                tabIndex={-1}
                onMouseDown={(event) => {
                  event.preventDefault();
                  choose(document);
                }}
                onMouseEnter={() => setChoice(index)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left",
                  index === choice ? "bg-surface-2" : "hover:bg-surface-2/60",
                )}
              >
                {document.scope === "table" ? (
                  <Database aria-hidden className="size-4 shrink-0 text-accent" />
                ) : (
                  <FileText aria-hidden className="size-4 shrink-0 text-subtle" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium">
                    @{document.mention}
                  </span>
                  <span className="block truncate text-[11.5px] text-subtle">
                    {document.scope === "table"
                      ? document.filename
                      : `${document.filename} · ${document.scope === "chat" ? "this chat" : "space"}`}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {files && files.attachments.length > 0 && (
        <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Attached documents">
          {files.attachments.map((attachment) => (
            <li
              key={attachment.key}
              title={attachment.error}
              className={cn(
                "flex max-w-[15rem] items-center gap-1.5 rounded-lg border py-0.5 pr-0.5 pl-2 text-[12px]",
                attachment.status === "failed"
                  ? "border-danger/40 bg-danger-soft"
                  : "border-border bg-surface-2/60",
              )}
            >
              {attachment.status === "uploading" ? (
                <LoaderCircle aria-hidden className="size-3.5 shrink-0 animate-spin text-accent" />
              ) : attachment.status === "failed" ? (
                <CircleAlert aria-hidden className="size-3.5 shrink-0 text-danger" />
              ) : (
                <FileText aria-hidden className="size-3.5 shrink-0 text-subtle" />
              )}
              <span className="truncate">{attachment.filename}</span>
              {attachment.status === "uploading" && (
                <span className="shrink-0 text-subtle">Reading…</span>
              )}
              {attachment.status === "failed" && (
                <span className="truncate text-danger">{attachment.error ?? "failed"}</span>
              )}
              <button
                type="button"
                aria-label={`Remove ${attachment.filename}`}
                disabled={attachment.status === "uploading"}
                onClick={() => files.onRemove(attachment)}
                className="flex size-5 shrink-0 items-center justify-center rounded text-subtle transition-colors hover:bg-surface-2 hover:text-fg disabled:opacity-40"
              >
                <X aria-hidden className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <label htmlFor="composer" className="sr-only">
        Your question
      </label>
      <div className="relative">
        <div
          ref={backdrop}
          aria-hidden
          className="pointer-events-none absolute inset-0 overflow-hidden px-1 text-[15px] leading-6 break-words whitespace-pre-wrap text-fg"
        >
          {files && files.documents.length > 0
            ? splitMentions(
                text,
                files.documents.map((d) => d.mention),
              ).map((part, index) => {
                if (!part.mention) return <span key={index}>{part.text}</span>;
                const lead = /^\s*/.exec(part.text)?.[0] ?? "";
                return (
                  <span key={index}>
                    {lead}
                    <mark className="rounded-[4px] bg-accent/15 text-accent">
                      {part.text.slice(lead.length)}
                    </mark>
                  </span>
                );
              })
            : text}
          {"​"}
        </div>
        <textarea
          id="composer"
          ref={area}
          rows={1}
          maxLength={MAX_LENGTH}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            setCaret(event.target.selectionStart);
            setChoice(0);
            measure();
          }}
          onScroll={(event) => {
            if (backdrop.current) backdrop.current.scrollTop = event.currentTarget.scrollTop;
          }}
          onSelect={(event) => setCaret(event.currentTarget.selectionStart)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          className="relative block max-h-[200px] min-h-7 w-full resize-none [scrollbar-width:none] bg-transparent px-1 text-[15px] leading-6 text-transparent caret-[var(--text)] placeholder:text-subtle focus-visible:outline-none [&::-webkit-scrollbar]:hidden"
        />
      </div>
      <div className="mt-2 flex items-center gap-1.5">
        {files && (
          <>
            <input
              ref={picker}
              type="file"
              hidden
              multiple
              accept={ATTACH_TYPES}
              onChange={(event) => {
                if (event.target.files?.length) files.onAttach([...event.target.files]);
                event.target.value = "";
              }}
            />
            <Button
              variant="ghost"
              size="icon"
              aria-label="Attach documents"
              title="Attach documents to this chat"
              onClick={() => picker.current?.click()}
            >
              <Paperclip aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Mention a table or document"
              title="Mention a table or document with @"
              onClick={() => {
                const element = area.current;
                if (!element) return;
                const position = element.selectionStart ?? text.length;
                const spacer = position > 0 && !/\s$/.test(text.slice(0, position)) ? " " : "";
                const next = `${text.slice(0, position)}${spacer}@${text.slice(position)}`;
                const at = position + spacer.length + 1;
                setText(next);
                setCaret(at);
                measure();
                requestAnimationFrame(() => {
                  element.focus();
                  element.setSelectionRange(at, at);
                });
              }}
            >
              <AtSign aria-hidden />
            </Button>
          </>
        )}
        {toolbar}
        <div className="ml-auto flex items-center gap-2">
          {trailing}
          {text.length > MAX_LENGTH - 200 && (
            <span className="text-[12px] text-subtle tabular-nums">
              {text.length}/{MAX_LENGTH}
            </span>
          )}
          <Button
            type="submit"
            variant="primary"
            size="icon"
            className="size-9 rounded-full disabled:bg-surface-2 disabled:text-subtle disabled:opacity-100 disabled:shadow-none"
            aria-label={running ? "Stop" : "Send"}
            disabled={!running && empty}
          >
            {running ? (
              <Square aria-hidden className="size-3.5 fill-current" />
            ) : (
              <ArrowUp aria-hidden />
            )}
          </Button>
        </div>
      </div>
    </form>
  );
}
