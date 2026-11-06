import { GitBranch, History, Pencil, Settings2, X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { Button } from "../../components/ui/Button";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { ApiError, asApiError } from "../../lib/api";
import { useUnloadWarning } from "../../lib/useUnloadWarning";
import { cn } from "../../lib/cn";
import { useDocuments, useSpace, useTables } from "../spaces/queries";
import { AnswerCard } from "./AnswerCard";
import { viewOfLive, viewOfMessage } from "./answerView";
import { Composer, type Attachment, type ComposerFiles } from "./Composer";
import { ConversationList } from "./ConversationList";
import { useAuth } from "../../lib/auth";
import { rememberChat, rememberSpace } from "./lastSpace";
import { getAnswerStyle } from "./answerStyle";
import { ShareButton } from "./ShareButton";
import { AnswerStyleMenu } from "./AnswerStyleMenu";
import { useSidebar, useWideScreen } from "./sidebar";
import { SidebarResizer } from "./SidebarResizer";
import { parseMentions, splitMentions, tableMention, type Mentionable } from "./mentions";
import {
  useChatDocuments,
  useConversation,
  useCreateConversation,
  useDeleteChatDocument,
  useForkConversation,
  useRefreshChat,
  useUploadChatDocument,
} from "./queries";
import { SpaceSwitcher } from "./SpaceSwitcher";
import type { ChatMessage, LiveTurn, Mention } from "./types";
import { useAsk } from "./useAsk";
import { Welcome } from "./Welcome";

interface SendOptions {
  replaceMessageId?: string;
  replaceSeq?: number;
  mentions?: Mention[];
}

/** The chat for one space (or the general chat): history on the left, the thread on the right. */
export function ChatPage() {
  const { spaceId = "", conversationId } = useParams();
  const navigate = useNavigate();
  const space = useSpace(spaceId);
  const conversation = useConversation(spaceId, conversationId);
  const createConversation = useCreateConversation(spaceId);
  const refresh = useRefreshChat(spaceId);
  const fork = useForkConversation(spaceId);
  const { live, ask, resume, stop, clear } = useAsk(spaceId);
  const [listOpen, setListOpen] = useState(false);
  const { width } = useSidebar();
  const wide = useWideScreen();
  const aside = useRef<HTMLElement>(null);

  const [startError, setStartError] = useState<string | null>(null);

  // Documents: the ones added in this chat, the space's own, and uploads still in flight.
  const chatDocuments = useChatDocuments(spaceId, conversationId);
  const spaceDocuments = useDocuments(spaceId);
  const spaceTables = useTables(spaceId);
  const uploadDocument = useUploadChatDocument(spaceId);
  const deleteDocument = useDeleteChatDocument(spaceId);
  const [pending, setPending] = useState<Attachment[]>([]);
  const inFlight = useRef(new Set<string>());
  // A file still on its way would be cut off by a refresh, so ask first.
  useUnloadWarning(pending.some((a) => a.status === "uploading"));

  useEffect(() => {
    if (space.data) rememberSpace(spaceId);
  }, [space.data, spaceId]);

  // So "Ask" in the menu brings you back here: the space, and the conversation once it is open
  // (a chat that failed to load, or was deleted, is not remembered).
  const { user } = useAuth();
  useEffect(() => {
    if (!user || !space.data) return;
    if (!conversationId) rememberChat(user.id, spaceId, null);
    else if (conversation.data) rememberChat(user.id, spaceId, conversationId);
  }, [user, space.data, spaceId, conversationId, conversation.data]);

  // Opening another conversation drops whatever was streaming for the previous one.
  const shownFor = useRef(conversationId);
  useEffect(() => {
    if (shownFor.current !== conversationId && !live?.running) clear();
    shownFor.current = conversationId;
  }, [conversationId, live?.running, clear]);

  const mentionable = useMemo<Mentionable[]>(
    () => [
      ...(space.data?.is_personal ? [] : (spaceTables.data ?? []))
        .filter((t) => t.columns.length > 0)
        .map((t) => ({
          id: t.id,
          mention: tableMention(t.name),
          filename: t.row_count >= 0 ? `Table · ${t.row_count.toLocaleString()} rows` : "Table",
          scope: "table" as const,
        })),
      ...(chatDocuments.data ?? [])
        .filter((d) => d.status === "ready")
        .map((d) => ({
          id: d.id,
          mention: d.mention,
          filename: d.filename,
          scope: "chat" as const,
        })),
      ...(spaceDocuments.data ?? [])
        .filter((d) => d.status === "ready")
        .map((d) => ({
          id: d.id,
          mention: d.mention,
          filename: d.filename,
          scope: "space" as const,
        })),
    ],
    [chatDocuments.data, spaceDocuments.data, spaceTables.data, space.data?.is_personal],
  );

  /** The conversation to work in, made (and opened) the first time something needs it. */
  const creating = useRef<Promise<string> | null>(null);
  async function ensureConversation(): Promise<string> {
    if (conversationId) return conversationId;
    creating.current ??= createConversation
      .mutateAsync()
      .then((created) => {
        void navigate(`/spaces/${spaceId}/chat/${created.id}`);
        return created.id;
      })
      .finally(() => {
        creating.current = null;
      });
    return creating.current;
  }

  async function attach(files: File[]) {
    setStartError(null);
    let target: string;
    try {
      target = await ensureConversation();
    } catch (caught) {
      setStartError(asApiError(caught).message);
      return;
    }
    for (const file of files) {
      // The same file picked twice (or a double drop) is added once.
      const same = (name: string) => name.toLowerCase() === file.name.toLowerCase();
      const already =
        (chatDocuments.data ?? []).some((d) => same(d.filename)) ||
        inFlight.current.has(file.name.toLowerCase());
      if (already) continue;
      inFlight.current.add(file.name.toLowerCase());
      const key = `${file.name}-${file.size}-${Date.now()}-${Math.random()}`;
      setPending((list) => [...list, { key, filename: file.name, status: "uploading" }]);
      try {
        await uploadDocument.mutateAsync({ conversationId: target, file });
        setPending((list) => list.filter((a) => a.key !== key));
        inFlight.current.delete(file.name.toLowerCase());
      } catch (caught) {
        inFlight.current.delete(file.name.toLowerCase());
        const message = asApiError(caught).message;
        setPending((list) =>
          list.map((a) => (a.key === key ? { ...a, status: "failed", error: message } : a)),
        );
      }
    }
  }

  const attachments: Attachment[] = [
    ...(chatDocuments.data ?? []).map<Attachment>((d) => ({
      key: d.id,
      id: d.id,
      filename: d.filename,
      status: d.status === "ready" ? "ready" : d.status === "processing" ? "uploading" : "failed",
      error: d.error ?? undefined,
    })),
    ...pending,
  ];

  const files: ComposerFiles = {
    documents: mentionable,
    attachments,
    onAttach: (list) => void attach(list),
    onRemove: (attachment) => {
      if (attachment.id && conversationId) {
        deleteDocument.mutate({ conversationId, id: attachment.id });
      } else {
        setPending((list) => list.filter((a) => a.key !== attachment.key));
      }
    },
  };

  async function send(question: string, options: SendOptions = {}) {
    setStartError(null);
    let target: string;
    try {
      target = await ensureConversation();
    } catch (caught) {
      setStartError(asApiError(caught).message);
      return;
    }
    const chosen = getAnswerStyle();
    await ask(target, question, {
      ...options,
      mode: personal && chosen === "deep" ? "standard" : chosen,
    });
    await refresh(target);
    clear();
  }

  /** A question typed in the box: the documents it points at with @ are worked out here. */
  function submit(text: string) {
    void send(text, { mentions: parseMentions(text, mentionable) });
  }

  // An answer still being written when the page was refreshed keeps running on the server:
  // rejoin it instead of showing it as stopped.
  const rejoined = useRef<string | null>(null);
  const unfinished = conversation.data?.messages.at(-1);
  useEffect(() => {
    if (
      !conversationId ||
      live ||
      conversation.data?.mine === false ||
      unfinished?.status !== "running"
    )
      return;
    if (rejoined.current === unfinished.id) return;
    rejoined.current = unfinished.id;
    void resume(conversationId, unfinished).then(async () => {
      await refresh(conversationId);
      clear();
    });
  }, [conversationId, live, conversation.data?.mine, unfinished, resume, refresh, clear]);

  if (space.isPending) {
    return (
      <div className="space-y-3 p-8">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (space.isError) {
    const missing = space.error instanceof ApiError && space.error.status === 404;
    return (
      <div className="mx-auto max-w-xl p-8">
        <Notice
          tone="error"
          title={missing ? "This space doesn't exist" : "Could not load the space"}
        >
          {missing ? "It may have been removed, or you are not a member." : space.error.message}{" "}
          <Link to="/chat" className="underline">
            Go to the general chat
          </Link>
        </Notice>
      </div>
    );
  }

  const personal = Boolean(space.data.is_personal);
  const editor = space.data.my_role === "editor" && !personal;
  // The centred start screen stays until the first question is sent: attaching documents
  // (which creates the conversation) does not move the box.
  const hasMessages = (conversation.data?.messages.length ?? 0) > 0;
  const opening = Boolean(conversationId) && conversation.isPending;
  // A chat that failed to load shows why, not the start screen as if it were empty.
  const failed = Boolean(conversationId) && conversation.isError;
  const showWelcome = !live && !hasMessages && !opening && !failed;
  // A chat another member shared can be read and branched, not continued here.
  const readOnly = conversation.data?.mine === false;

  function branch(messageId?: string) {
    if (!conversationId) return;
    fork.mutate(
      { id: conversationId, messageId },
      { onSuccess: (made) => void navigate(`/spaces/${spaceId}/chat/${made.id}`) },
    );
  }

  return (
    <div className="relative flex h-full min-h-0">
      <aside
        ref={aside}
        id="chat-sidebar"
        style={{ "--sidebar-width": `${width}px` } as CSSProperties}
        className={cn(
          "relative z-10 w-[17rem] shrink-0 border-r border-border bg-surface md:relative md:block md:w-[var(--sidebar-width)] md:max-w-[45vw]",
          "data-[dragging=true]:transition-none md:transition-[width] md:duration-200",
          listOpen ? "absolute inset-y-0 left-0 block" : "hidden",
        )}
      >
        <ConversationList
          spaceId={spaceId}
          activeId={conversationId}
          onNew={() => {
            clear();
            setListOpen(false);
            void navigate(`/spaces/${spaceId}/chat`);
          }}
          onSelect={(id) => {
            setListOpen(false);
            void navigate(`/spaces/${spaceId}/chat/${id}`);
          }}
          onDeleted={(id) => id === conversationId && void navigate(`/spaces/${spaceId}/chat`)}
        />
        {wide && <SidebarResizer aside={aside} />}
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-3 md:px-5">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label={listOpen ? "Close history" : "Open history"}
            onClick={() => setListOpen((open) => !open)}
          >
            {listOpen ? <X aria-hidden /> : <History aria-hidden />}
          </Button>
          <SpaceSwitcher current={space.data} />
          <div className="ml-auto flex items-center gap-2">
            {conversationId && hasMessages && !readOnly && (
              <ShareButton
                spaceId={spaceId}
                conversationId={conversationId}
                title={conversation.data?.title ?? "Chat"}
                shared={Boolean(conversation.data?.shared)}
                personal={personal}
              />
            )}
            {editor && (
              <Link
                to={`/spaces/${spaceId}`}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 text-[13px] font-medium text-muted shadow-card transition-colors hover:border-border-strong hover:text-fg"
              >
                <Settings2 aria-hidden className="size-3.5" />
                Configure
              </Link>
            )}
          </div>
        </header>

        {showWelcome ? (
          <Welcome
            spaceId={spaceId}
            spaceName={space.data.name}
            personal={personal}
            files={files}
            onAsk={submit}
          />
        ) : (
          <Thread
            spaceId={spaceId}
            conversationId={conversationId}
            editor={editor}
            personal={personal}
            live={live}
            loading={conversation.isPending && Boolean(conversationId) && !live}
            error={conversation.isError ? conversation.error.message : null}
            messages={conversation.data?.messages ?? []}
            startError={startError}
            files={files}
            mentionable={mentionable}
            onAsk={(question, options) => void send(question, options)}
            onSubmit={submit}
            onStop={stop}
            readOnly={readOnly}
            ownerName={conversation.data?.owner_name ?? null}
            onBranch={personal ? undefined : branch}
            branching={fork.isPending}
          />
        )}
      </section>
    </div>
  );
}

function Thread({
  spaceId,
  conversationId,
  editor,
  personal,
  live,
  loading,
  error,
  messages,
  startError,
  files,
  mentionable,
  onAsk,
  onSubmit,
  onStop,
  readOnly,
  ownerName,
  onBranch,
  branching,
}: {
  spaceId: string;
  conversationId: string | undefined;
  editor: boolean;
  personal: boolean;
  live: LiveTurn | null;
  loading: boolean;
  error: string | null;
  messages: ChatMessage[];
  startError: string | null;
  files: ComposerFiles;
  mentionable: Mentionable[];
  onAsk: (question: string, options?: SendOptions) => void;
  onSubmit: (text: string) => void;
  onStop: () => void;
  readOnly: boolean;
  ownerName: string | null;
  onBranch?: (messageId?: string) => void;
  branching: boolean;
}) {
  const bottom = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const running = Boolean(live?.running);

  // What is saved, without the turn that is being (re)written right now.
  const saved = messages.filter(
    (m) => m.id !== live?.messageId && (live?.replaceSeq == null || m.seq < live.replaceSeq),
  );
  const lastSaved = saved.at(-1);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [saved.length, live?.stage, live?.answer, live?.thoughts.length, live?.finished]);

  return (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto" role="log" aria-label="Conversation">
        <div className="mx-auto w-full max-w-4xl space-y-10 px-5 py-8 md:px-8">
          {loading && (
            <>
              <Skeleton className="ml-auto h-10 w-2/3" />
              <Skeleton className="h-40" />
            </>
          )}
          {error && (
            <Notice tone="error" title="Could not load this conversation">
              {error}
            </Notice>
          )}
          {saved.map((message) => (
            <Turn
              key={message.id}
              question={message.question}
              mentions={message.mentions.map((m) => m.name)}
              canEdit={!running && !readOnly}
              editing={editing === message.id}
              onEdit={() => setEditing(message.id)}
              onCancelEdit={() => setEditing(null)}
              onResend={(text) => {
                setEditing(null);
                onAsk(text, {
                  replaceMessageId: message.id,
                  replaceSeq: message.seq,
                  mentions: parseMentions(text, mentionable),
                });
              }}
            >
              <AnswerCard
                view={viewOfMessage(message)}
                spaceId={spaceId}
                conversationId={conversationId ?? ""}
                editor={editor}
                readOnly={readOnly}
                isLast={message.id === lastSaved?.id && !live && !readOnly}
                onAsk={(question) => onAsk(question)}
                onStop={onStop}
                onBranch={onBranch ? (id) => onBranch(id) : undefined}
              />
            </Turn>
          ))}
          {live && (
            <Turn
              question={live.question}
              mentions={live.mentions.map((m) => m.name)}
              canEdit={false}
              editing={false}
            >
              <AnswerCard
                view={viewOfLive(live)}
                spaceId={spaceId}
                conversationId={conversationId ?? ""}
                editor={editor}
                isLast
                onAsk={(question) => onAsk(question)}
                onStop={onStop}
              />
            </Turn>
          )}
          {startError && (
            <Notice tone="error" title="Could not start the conversation">
              {startError}
            </Notice>
          )}
          <div ref={bottom} />
        </div>
      </div>
      <motion.div
        initial={{ opacity: 0.4, y: -160 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        className="shrink-0 bg-bg/80 px-4 pt-2 pb-3 backdrop-blur"
      >
        <div className="mx-auto w-full max-w-4xl md:px-4">
          {readOnly ? (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3">
              <p className="min-w-0 flex-1 text-[13.5px] text-muted">
                {ownerName ?? "Someone"} shared this chat with the space. You can read it, but not
                add to it.
              </p>
              {onBranch && (
                <Button variant="primary" size="sm" loading={branching} onClick={() => onBranch()}>
                  <GitBranch aria-hidden className="size-3.5" />
                  Branch into my own chat
                </Button>
              )}
            </div>
          ) : (
            <Composer
              running={running}
              onStop={onStop}
              onSend={onSubmit}
              files={files}
              trailing={<AnswerStyleMenu deep={!personal} />}
              placeholder={
                personal
                  ? "Message the assistant. Type @ to point at a document"
                  : "Ask a follow-up question. Type @ to point at a table or document"
              }
            />
          )}
          <p className="mt-1.5 text-center text-[12px] text-subtle">
            {personal
              ? "Answers can be wrong. Check important details yourself."
              : "Answers come from your data. Check the SQL before relying on a number."}
          </p>
        </div>
      </motion.div>
    </>
  );
}

export function Turn({
  question,
  mentions,
  canEdit,
  editing,
  onEdit,
  onCancelEdit,
  onResend,
  children,
}: {
  question: string;
  mentions: string[];
  canEdit: boolean;
  editing: boolean;
  onEdit?: () => void;
  onCancelEdit?: () => void;
  onResend?: (text: string) => void;
  children: React.ReactNode;
}) {
  const [text, setText] = useState(question);

  return (
    <div className="space-y-4">
      <div className="group flex justify-end gap-2">
        {editing ? (
          <div className="w-full max-w-[85%] space-y-2 rounded-2xl border border-accent bg-surface p-3">
            <label htmlFor="edit-question" className="sr-only">
              Edit your question
            </label>
            <textarea
              id="edit-question"
              autoFocus
              rows={2}
              maxLength={2000}
              value={text}
              onChange={(event) => setText(event.target.value)}
              className="block w-full resize-y bg-transparent text-[14px] leading-6 focus-visible:outline-none"
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={onCancelEdit}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="primary"
                disabled={!text.trim() || text.trim() === question}
                onClick={() => onResend?.(text.trim())}
              >
                Resend
              </Button>
            </div>
            <p className="text-[12px] text-subtle">
              Answers after this question are replaced by the new answer.
            </p>
          </div>
        ) : (
          <>
            {canEdit && onEdit && (
              <Button
                variant="ghost"
                size="icon"
                className="self-center opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
                aria-label="Edit this question"
                onClick={() => {
                  setText(question);
                  onEdit();
                }}
              >
                <Pencil aria-hidden />
              </Button>
            )}
            <p className="max-w-[85%] rounded-2xl rounded-tr-md bg-accent-soft px-4 py-3 text-[15.5px] leading-7 whitespace-pre-wrap">
              {splitMentions(question, mentions).map((part, index) =>
                part.mention ? (
                  <span key={index} className="rounded bg-accent/15 px-1 font-medium text-accent">
                    {part.text}
                  </span>
                ) : (
                  <span key={index}>{part.text}</span>
                ),
              )}
            </p>
          </>
        )}
      </div>
      {children}
    </div>
  );
}
