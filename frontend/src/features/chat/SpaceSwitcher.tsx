import { Check, ChevronsUpDown, Database, MessageCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { cn } from "../../lib/cn";
import { plural } from "../../lib/format";
import { useSpaces } from "../spaces/queries";
import type { Space } from "../spaces/types";
import { useGeneralSpace } from "./queries";

/**
 * Choose what the chat talks about: the general chat (documents you add), or one of your
 * spaces (its tables, rules and documents). Picking one starts a new chat there.
 */
export function SpaceSwitcher({ current }: { current: Space }) {
  const navigate = useNavigate();
  const spaces = useSpaces();
  const general = useGeneralSpace();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") setOpen(false);
      } else if (root.current && !root.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const personal = current.is_personal;
  const options: Array<{ id: string; name: string; hint: string; general: boolean }> = [
    ...(general.data
      ? [
          {
            id: general.data.id,
            name: "General chat",
            hint: "Your documents, no data",
            general: true,
          },
        ]
      : []),
    ...(spaces.data ?? []).map((space) => ({
      id: space.id,
      name: space.name,
      hint: plural(space.table_count, "table"),
      general: false,
    })),
  ];

  return (
    <div ref={root} className="relative min-w-0">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="group -ml-1 flex min-w-0 items-center gap-2.5 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-surface-2"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2 text-accent">
          {personal ? (
            <MessageCircle aria-hidden className="size-4" />
          ) : (
            <Database aria-hidden className="size-4" />
          )}
        </span>
        <span className="min-w-0">
          <span className="flex items-center gap-1 text-[14px] leading-tight font-semibold">
            <span className="truncate">{personal ? "General chat" : current.name}</span>
            <ChevronsUpDown aria-hidden className="size-3.5 shrink-0 text-subtle" />
          </span>
          <span className="block truncate text-[12px] leading-tight text-subtle">
            {personal
              ? "Ask about documents you add"
              : `${plural(current.table_count, "table")}${current.my_role === "editor" ? "" : " · view only"}`}
          </span>
        </span>
      </button>

      {open && (
        <ul
          role="listbox"
          aria-label="Choose a space"
          className="absolute top-full left-0 z-30 mt-1.5 max-h-80 w-72 overflow-y-auto rounded-xl border border-border bg-surface p-1 shadow-lg"
        >
          {options.map((option) => {
            const selected = option.id === current.id;
            return (
              <li key={option.id} role="option" aria-selected={selected}>
                <button
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    if (!selected) void navigate(`/spaces/${option.id}/chat`);
                  }}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors",
                    selected ? "bg-surface-2" : "hover:bg-surface-2/60",
                  )}
                >
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2 text-subtle">
                    {option.general ? (
                      <MessageCircle aria-hidden className="size-3.5" />
                    ) : (
                      <Database aria-hidden className="size-3.5" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium">{option.name}</span>
                    <span className="block truncate text-[11.5px] text-subtle">{option.hint}</span>
                  </span>
                  {selected && <Check aria-hidden className="size-4 shrink-0 text-accent" />}
                </button>
              </li>
            );
          })}
          {spaces.isPending && (
            <li className="px-3 py-2 text-[12.5px] text-subtle">Loading spaces…</li>
          )}
        </ul>
      )}
    </div>
  );
}
