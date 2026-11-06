import { Check, Copy, LoaderCircle, Search, X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useId, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "../../components/ui/Button";
import { Notice } from "../../components/ui/Notice";
import { Switch } from "../../components/ui/Switch";
import { asApiError } from "../../lib/api";
import { initials, timeAgo } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import { useSetShares, useShareConversation, useShares, usePeople, type Person } from "./queries";

/**
 * Who can read this chat: search for people and tick them, then Save. People you leave out lose
 * it. Readers can open the documents the answers cite, and branch a copy of their own.
 */
export function ShareDialog({
  spaceId,
  conversationId,
  title,
  everyone,
  personal,
  onClose,
}: {
  spaceId: string;
  conversationId: string;
  title: string;
  everyone: boolean;
  personal: boolean;
  onClose: () => void;
}) {
  const heading = useId();
  const current = useShares(spaceId, conversationId);
  const save = useSetShares(spaceId, conversationId);
  const wide = useShareConversation(spaceId);
  const [text, setText] = useState("");
  const query = useDebounced(text, 200);
  const found = usePeople(query.trim());
  // null until the person changes something: then it is the chosen set, otherwise what is saved.
  const [draft, setDraft] = useState<Map<string, Person> | null>(null);
  const [copied, setCopied] = useState(false);

  const saved = useMemo(
    () => new Map((current.data?.people ?? []).map((p) => [p.id, p as Person])),
    [current.data],
  );
  const chosen = draft ?? saved;
  const changed =
    draft !== null && (draft.size !== saved.size || [...draft.keys()].some((id) => !saved.has(id)));
  const seen = new Map((current.data?.people ?? []).map((p) => [p.id, p.seen_at]));
  const error = save.error ?? wide.error;

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

  function toggle(person: Person) {
    setDraft((now) => {
      const next = new Map(now ?? saved);
      if (next.has(person.id)) next.delete(person.id);
      else next.set(person.id, person);
      return next;
    });
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/shared/${conversationId}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be blocked; nothing else to do.
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6">
      <motion.div
        aria-hidden
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1, transition: { duration: 0.18 } }}
      />
      <motion.div
        role="dialog"
        aria-modal="true"
        aria-labelledby={heading}
        className="relative flex max-h-[88dvh] w-full flex-col overflow-hidden rounded-t-2xl border border-border bg-surface shadow-2xl sm:max-w-lg sm:rounded-2xl"
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
            <h2 id={heading} className="text-[16px] font-semibold">
              Share this chat
            </h2>
            <p className="truncate text-[13px] text-muted">{title}</p>
          </div>
          <Button size="icon" variant="ghost" aria-label="Close" onClick={onClose}>
            <X aria-hidden />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
          {error && (
            <Notice tone="error" title="That did not work">
              {asApiError(error).message}
            </Notice>
          )}

          <section aria-label="People" className="space-y-2.5">
            <label className="flex h-10 items-center gap-2 rounded-lg border border-border bg-surface-2/60 px-3 focus-within:ring-2 focus-within:ring-accent/40">
              <Search aria-hidden className="size-4 shrink-0 text-subtle" />
              <input
                value={text}
                onChange={(event) => setText(event.target.value)}
                aria-label="Find people"
                placeholder="Find someone by name or email"
                className="h-full w-full bg-transparent text-[14px] outline-none placeholder:text-subtle"
              />
              {found.isFetching && (
                <LoaderCircle aria-hidden className="size-4 shrink-0 animate-spin text-subtle" />
              )}
            </label>
            <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border">
              {(found.data ?? []).length === 0 && !found.isPending && (
                <li className="px-3 py-4 text-center text-[13px] text-muted">
                  Nobody matches that.
                </li>
              )}
              {(found.data ?? []).map((person) => {
                const on = chosen.has(person.id);
                return (
                  <li key={person.id}>
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={on}
                      onClick={() => toggle(person)}
                      className="flex w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-surface-2/60"
                    >
                      <Avatar name={person.full_name} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-medium">
                          {person.full_name}
                        </span>
                        <span className="block truncate text-[12.5px] text-subtle">
                          {person.email}
                        </span>
                      </span>
                      <span
                        aria-hidden
                        className={
                          on
                            ? "flex size-5 items-center justify-center rounded-md bg-accent text-accent-fg"
                            : "size-5 rounded-md border border-border-strong"
                        }
                      >
                        {on && <Check className="size-3.5" />}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>

          <section aria-label="Who has access" className="space-y-2">
            <h3 className="text-[11px] font-semibold tracking-wide text-subtle uppercase">
              {chosen.size === 0 ? "Only you" : `Shared with ${chosen.size}`}
            </h3>
            {chosen.size > 0 && (
              <ul className="space-y-1.5">
                {[...chosen.values()].map((person) => {
                  const opened = seen.get(person.id);
                  return (
                    <li key={person.id} className="flex items-center gap-3">
                      <Avatar name={person.full_name} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px]">{person.full_name}</span>
                        <span className="block text-[12px] text-subtle">
                          {saved.has(person.id)
                            ? opened
                              ? `Opened ${timeAgo(opened)}`
                              : "Not opened yet"
                            : "Will be told when you save"}
                        </span>
                      </span>
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label={`Stop sharing with ${person.full_name}`}
                        onClick={() => toggle(person)}
                      >
                        <X aria-hidden />
                      </Button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {!personal && (
            <label className="flex cursor-pointer items-start justify-between gap-4 rounded-lg border border-border p-3">
              <span>
                <span className="block text-[14px] font-medium">Everyone in this space</span>
                <span className="block text-[12.5px] text-muted">
                  Any member of the space can read this chat.
                </span>
              </span>
              <Switch
                aria-label="Share with everyone in this space"
                checked={everyone}
                disabled={wide.isPending}
                onChange={(next) => wide.mutate({ id: conversationId, shared: next })}
              />
            </label>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-border bg-surface-2/40 px-5 py-3.5">
          <Button size="sm" onClick={() => void copy()} disabled={chosen.size === 0 && !everyone}>
            {copied ? (
              <Check aria-hidden className="size-3.5" />
            ) : (
              <Copy aria-hidden className="size-3.5" />
            )}
            {copied ? "Copied" : "Copy link"}
          </Button>
          <span className="ml-auto flex gap-2">
            <Button onClick={onClose}>{changed ? "Cancel" : "Done"}</Button>
            {changed && (
              <Button
                variant="primary"
                loading={save.isPending}
                onClick={() =>
                  save.mutate([...(draft ?? saved).keys()], { onSuccess: () => setDraft(null) })
                }
              >
                Save
              </Button>
            )}
          </span>
        </div>
      </motion.div>
    </div>,
    document.body,
  );
}

function Avatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent"
    >
      {initials(name)}
    </span>
  );
}
