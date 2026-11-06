import { Check, ChevronDown } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { cn } from "../../lib/cn";

export interface SelectOption {
  value: string;
  label: string;
  /** A line under the label in the list, for choices that need explaining. */
  description?: string;
  icon?: ReactNode;
}

const MAX_HEIGHT = 264;
const GAP = 4;

/**
 * A drop-down list drawn in the app's own colors, in place of the browser's. It follows the
 * combobox pattern: the button keeps focus, arrow keys move through the options, Enter or Space
 * chooses, Escape closes, and typing a letter jumps to the next option that starts with it. The
 * list is drawn in the page body so no card or collapsing panel can clip it, and opens upward
 * when there is no room below.
 */
export function Select({
  options,
  value,
  onChange,
  labelId,
  ariaLabel,
  variant = "field",
  menuWidth,
  align = "start",
  className,
  disabled,
  id,
  name,
}: {
  options: SelectOption[];
  value?: string;
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void;
  /** The id of the element that names the control (its visible or hidden label). */
  labelId?: string;
  /** Names the control when there is no label element to point at. */
  ariaLabel?: string;
  /** field: a form field. pill: a small round button for a toolbar, whose list can be wider. */
  variant?: "field" | "pill";
  menuWidth?: number;
  /** Which edge of the button the list lines up with. */
  align?: "start" | "end";
  className?: string;
  disabled?: boolean;
  id?: string;
  name?: string;
}) {
  const listId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [place, setPlace] = useState<{ top: number; left: number; width: number; up: boolean }>();

  const selected = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );
  const shown = options.find((option) => option.value === value) ?? options[0];

  const position = useCallback(() => {
    const box = button.current?.getBoundingClientRect();
    if (!box) return;
    const room = window.innerHeight - box.bottom;
    const up = room < Math.min(MAX_HEIGHT, options.length * 36 + 8) && box.top > room;
    const width = Math.max(box.width, menuWidth ?? 0);
    const left = align === "end" ? box.right - width : box.left;
    setPlace({
      top: up ? box.top - GAP : box.bottom + GAP,
      left: Math.max(8, Math.min(left, window.innerWidth - width - 8)),
      width,
      up,
    });
  }, [options.length, menuWidth, align]);

  useLayoutEffect(() => {
    if (open) position();
  }, [open, position]);

  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => {
      const target = event.target as Node;
      if (!button.current?.contains(target) && !list.current?.contains(target)) setOpen(false);
    };
    const follow = (event: Event) => {
      if (!list.current?.contains(event.target as Node)) position();
    };
    document.addEventListener("pointerdown", close);
    window.addEventListener("resize", position);
    window.addEventListener("scroll", follow, true);
    return () => {
      document.removeEventListener("pointerdown", close);
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", follow, true);
    };
  }, [open, position]);

  // Keep the option the keyboard is on in view.
  useEffect(() => {
    if (open) list.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  function choose(index: number) {
    const option = options[index];
    setOpen(false);
    button.current?.focus();
    if (!option || option.value === value) return;
    // Callers read `event.target.value`, as they did with the browser's own <select>.
    onChange?.({
      target: { value: option.value, name },
      currentTarget: { value: option.value, name },
    } as unknown as ChangeEvent<HTMLSelectElement>);
  }

  function openList() {
    setActive(selected);
    setOpen(true);
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;
    const last = options.length - 1;
    if (!open) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
        event.preventDefault();
        openList();
      }
      return;
    }
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setActive((index) => Math.min(index + 1, last));
        break;
      case "ArrowUp":
        event.preventDefault();
        setActive((index) => Math.max(index - 1, 0));
        break;
      case "Home":
        event.preventDefault();
        setActive(0);
        break;
      case "End":
        event.preventDefault();
        setActive(last);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        choose(active);
        break;
      case "Escape":
        event.preventDefault();
        setOpen(false);
        break;
      case "Tab":
        setOpen(false);
        break;
      default:
        if (event.key.length === 1 && !event.ctrlKey && !event.metaKey) {
          const letter = event.key.toLowerCase();
          const from = [...options.keys()].filter((i) => i > active);
          const next = [...from, ...options.keys()].find((i) =>
            options[i]?.label.toLowerCase().startsWith(letter),
          );
          if (next !== undefined) setActive(next);
        }
    }
  }

  return (
    <>
      <button
        ref={button}
        id={id}
        name={name}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-labelledby={labelId}
        aria-label={labelId ? undefined : ariaLabel}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openList())}
        onKeyDown={onKeyDown}
        className={cn(
          variant === "pill"
            ? "inline-flex h-8 items-center gap-1.5 rounded-full border border-border bg-transparent px-3 text-[13px] font-medium text-muted hover:border-border-strong hover:text-fg"
            : "flex h-9 w-full items-center justify-between gap-2 rounded-md border border-border bg-bg px-3 text-left text-[14px] text-fg hover:border-border-strong",
          "transition-[border-color,box-shadow,color] duration-150",
          "focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none",
          "disabled:opacity-60",
          open && (variant === "pill" ? "border-border-strong text-fg" : "border-accent"),
          className,
        )}
      >
        {variant === "pill" && shown?.icon && (
          <span aria-hidden className="[&_svg]:size-3.5">
            {shown.icon}
          </span>
        )}
        <span className="min-w-0 truncate">{shown?.label ?? ""}</span>
        <ChevronDown
          aria-hidden
          className={cn("size-4 shrink-0 text-subtle transition-transform", open && "rotate-180")}
        />
      </button>
      {open &&
        place &&
        createPortal(
          <ul
            ref={list}
            id={listId}
            role="listbox"
            aria-labelledby={labelId}
            style={{
              position: "fixed",
              left: place.left,
              width: place.width,
              maxHeight: MAX_HEIGHT,
              ...(place.up ? { bottom: window.innerHeight - place.top } : { top: place.top }),
            }}
            className="z-50 overflow-y-auto rounded-md border border-border-strong bg-surface p-1 text-[14px] text-fg shadow-card"
          >
            {options.map((option, index) => {
              const chosen = option.value === value;
              return (
                <li
                  key={option.value}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={chosen}
                  onPointerEnter={() => setActive(index)}
                  onClick={() => choose(index)}
                  className={cn(
                    "flex cursor-pointer items-start gap-2.5 rounded-[5px] px-2.5",
                    option.description ? "py-2" : "min-h-8 items-center py-1.5",
                    index === active && "bg-surface-2",
                  )}
                >
                  {option.icon && (
                    <span aria-hidden className="mt-0.5 text-muted [&_svg]:size-4">
                      {option.icon}
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate", chosen && "font-medium")}>
                      {option.label}
                    </span>
                    {option.description && (
                      <span className="mt-0.5 block text-[12.5px] leading-snug text-subtle">
                        {option.description}
                      </span>
                    )}
                  </span>
                  {chosen && <Check aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />}
                </li>
              );
            })}
          </ul>,
          document.body,
        )}
    </>
  );
}
