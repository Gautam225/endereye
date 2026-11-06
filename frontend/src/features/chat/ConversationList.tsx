import { Check, MessageSquare, Pencil, Pin, PinOff, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { Button } from "../../components/ui/Button";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import {
  useConversations,
  useDeleteConversation,
  usePinConversation,
  useRenameConversation,
  useSharedInbox,
} from "./queries";
import { groupConversations } from "./groups";
import type { Conversation } from "./types";

/** The thread history: search, new chat, pin, rename and delete. Its width is set by dragging. */
export function ConversationList({
  spaceId,
  activeId,
  onNew,
  onSelect,
  onDeleted,
}: {
  spaceId: string;
  activeId: string | undefined;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDeleted: (id: string) => void;
}) {
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const conversations = useConversations(spaceId, search);
  const shared = useSharedInbox();
  const navigate = useNavigate();
  const groups = useMemo(() => groupConversations(conversations.data ?? []), [conversations.data]);

  useEffect(() => {
    const timer = setTimeout(() => setSearch(text.trim()), 250);
    return () => clearTimeout(timer);
  }, [text]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-14 shrink-0 items-center px-4">
        <h2 className="text-[13px] font-semibold tracking-wide">Chats</h2>
      </div>
      <div className="space-y-2.5 px-3 pb-3">
        <Button variant="primary" className="w-full" onClick={onNew}>
          <Plus aria-hidden className="size-4" />
          New chat
        </Button>
        <label className="relative block">
          <span className="sr-only">Search chats</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-subtle"
          />
          <input
            id="chat-search"
            type="search"
            placeholder="Search chats"
            value={text}
            maxLength={200}
            onChange={(event) => setText(event.target.value)}
            className="h-8 w-full rounded-md border border-border bg-bg pr-2 pl-8 text-[13px] placeholder:text-subtle focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
          />
        </label>
      </div>
      <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {conversations.isPending ? (
          <div className="space-y-2 p-1">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : conversations.isError ? (
          <Notice tone="error" title="Could not load chats">
            {conversations.error.message}
          </Notice>
        ) : groups.length === 0 ? (
          <div className="flex flex-col items-center px-4 py-10 text-center">
            <span className="mb-3 flex size-9 items-center justify-center rounded-full border border-border bg-surface-2 text-subtle">
              <MessageSquare aria-hidden className="size-4" />
            </span>
            <p className="text-[13px] font-medium">
              {search ? "No chats match your search" : "No conversations yet"}
            </p>
            <p className="mt-1 text-[12.5px] text-subtle">
              {search ? "Try another word." : "Your questions and answers are saved here."}
            </p>
          </div>
        ) : (
          groups.map((group) => (
            <section key={group.name} className="mb-3">
              <h3 className="sticky top-0 z-[1] bg-surface px-2 pt-2 pb-1 text-[11px] font-semibold tracking-wide text-subtle uppercase">
                {group.name}
              </h3>
              <ul>
                {group.items.map((item) => (
                  <Row
                    key={item.id}
                    spaceId={spaceId}
                    item={item}
                    active={item.id === activeId}
                    onSelect={onSelect}
                    onDeleted={onDeleted}
                  />
                ))}
              </ul>
            </section>
          ))
        )}
        {!search && (shared.data?.length ?? 0) > 0 && (
          <section className="mb-3" aria-label="Shared with me">
            <h3 className="px-2 pt-2 pb-1 text-[11px] font-semibold tracking-wide text-subtle uppercase">
              Shared with me
            </h3>
            <ul>
              {shared.data?.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => void navigate(`/shared/${item.id}`)}
                    className="flex h-auto w-full flex-col items-start rounded-md px-2 py-1.5 text-left text-[13.5px] text-muted transition-colors hover:bg-surface-2/70 hover:text-fg"
                  >
                    <span className="flex w-full items-center gap-1.5">
                      <span className="min-w-0 flex-1 truncate">{item.title}</span>
                      {item.unread && (
                        <span
                          role="img"
                          aria-label="New"
                          className="size-2 shrink-0 rounded-full bg-accent"
                        />
                      )}
                    </span>
                    <span className="text-[12px] text-subtle">
                      {item.owner_name} · {item.space_name}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </nav>
    </div>
  );
}

function Row({
  spaceId,
  item,
  active,
  onSelect,
  onDeleted,
}: {
  spaceId: string;
  item: Conversation;
  active: boolean;
  onSelect: (id: string) => void;
  onDeleted: (id: string) => void;
}) {
  const rename = useRenameConversation(spaceId);
  const pin = usePinConversation(spaceId);
  const remove = useDeleteConversation(spaceId);
  const [mode, setMode] = useState<"view" | "rename" | "delete">("view");
  const [title, setTitle] = useState(item.title);
  const failure = rename.error ?? remove.error;

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = title.trim();
    if (!next || next === item.title) return setMode("view");
    rename.mutate({ id: item.id, title: next }, { onSuccess: () => setMode("view") });
  }

  if (mode === "rename") {
    return (
      <li className="px-1 py-0.5">
        <form onSubmit={submit} className="flex items-center gap-1">
          <input
            autoFocus
            aria-label="Conversation title"
            value={title}
            maxLength={200}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => event.key === "Escape" && setMode("view")}
            className="h-8 min-w-0 flex-1 rounded-md border border-accent bg-bg px-2 text-[13px] focus-visible:outline-none"
          />
          <Button
            type="submit"
            variant="ghost"
            size="icon"
            aria-label="Save title"
            loading={rename.isPending}
          >
            <Check aria-hidden />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Cancel" onClick={() => setMode("view")}>
            <X aria-hidden />
          </Button>
        </form>
        {failure && <p className="px-1 text-[12px] text-danger">{asApiError(failure).message}</p>}
      </li>
    );
  }

  if (mode === "delete") {
    return (
      <li className="flex items-center gap-1 rounded-md bg-danger-soft px-2 py-1">
        <span className="min-w-0 flex-1 truncate text-[13px]">Delete this chat?</span>
        <Button size="sm" variant="ghost" onClick={() => setMode("view")}>
          Keep
        </Button>
        <Button
          size="sm"
          className="text-danger"
          loading={remove.isPending}
          onClick={() => remove.mutate(item.id, { onSuccess: () => onDeleted(item.id) })}
        >
          Delete
        </Button>
      </li>
    );
  }

  return (
    <li
      className={cn(
        "group relative",
        active &&
          "before:absolute before:top-1.5 before:bottom-1.5 before:left-0 before:z-[1] before:w-0.5 before:rounded-full before:bg-accent",
      )}
    >
      <button
        type="button"
        aria-current={active ? "page" : undefined}
        onClick={() => onSelect(item.id)}
        className={cn(
          "flex h-9 w-full items-center gap-2 rounded-md px-2 pr-2 text-left text-[13.5px] transition-colors group-focus-within:pr-[5.25rem] group-hover:pr-[5.25rem]",
          active
            ? "bg-surface-2 font-medium text-fg"
            : "text-muted hover:bg-surface-2/70 hover:text-fg",
        )}
      >
        {item.pinned ? (
          <Pin aria-hidden className="size-3.5 shrink-0 text-accent" />
        ) : (
          <MessageSquare aria-hidden className="size-3.5 shrink-0 text-subtle" />
        )}
        <span className="truncate">{item.title}</span>
      </button>
      <div className="absolute top-1/2 right-1 hidden -translate-y-1/2 items-center group-focus-within:flex group-hover:flex">
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label={`${item.pinned ? "Unpin" : "Pin"} ${item.title}`}
          loading={pin.isPending}
          onClick={() => pin.mutate({ id: item.id, pinned: !item.pinned })}
        >
          {item.pinned ? (
            <PinOff aria-hidden className="size-3.5" />
          ) : (
            <Pin aria-hidden className="size-3.5" />
          )}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label={`Rename ${item.title}`}
          onClick={() => {
            setTitle(item.title);
            setMode("rename");
          }}
        >
          <Pencil aria-hidden className="size-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          aria-label={`Delete ${item.title}`}
          onClick={() => setMode("delete")}
        >
          <Trash2 aria-hidden className="size-3.5" />
        </Button>
      </div>
    </li>
  );
}
