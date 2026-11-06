import { Check, ChevronDown, Globe, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { cn } from "../../lib/cn";
import { currentName, filterZones, listZones, offsetOf, formatOffset } from "./timezones";

const SHOWN = 80; // rows drawn at once; a search narrows the rest

/**
 * Pick a real time zone from a list, by city or by offset. Each shows how far it is from UTC right
 * now, so "Asia/Kolkata  UTC+05:30" is clear without knowing the name.
 */
export function TimezonePicker({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (zone: string) => void;
}) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const zones = useMemo(() => listZones(), []);
  const found = useMemo(() => filterZones(zones, query).slice(0, SHOWN), [zones, query]);
  const shownValue = currentName(value);
  const offset = offsetOf(shownValue);

  useEffect(() => {
    if (!open) return;
    search.current?.focus();
    const away = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  function pick(zone: string) {
    onChange(zone);
    setOpen(false);
    setQuery("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((now) => Math.min(now + 1, found.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((now) => Math.max(now - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const choice = found[active];
      if (choice) pick(choice.id);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
  }

  return (
    <div ref={root} className="relative space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium">
        {label}
      </label>
      <button
        id={id}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((now) => !now)}
        className="flex h-10 w-full items-center gap-2 rounded-md border border-border bg-surface-2/60 px-3 text-left text-[14px] transition-colors hover:border-border-strong focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none"
      >
        <Globe aria-hidden className="size-4 shrink-0 text-subtle" />
        <span className="min-w-0 flex-1 truncate">{shownValue}</span>
        <span className="shrink-0 text-[12.5px] text-subtle">
          {offset === null ? "" : formatOffset(offset)}
        </span>
        <ChevronDown aria-hidden className="size-4 shrink-0 text-subtle" />
      </button>

      {open && (
        <div className="absolute z-30 mt-1 w-full min-w-72 overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Search aria-hidden className="size-4 shrink-0 text-subtle" />
            <input
              ref={search}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              role="combobox"
              aria-expanded
              aria-controls={`${id}-list`}
              aria-label="Search time zones"
              placeholder="Search a city or an offset, like +5:30"
              className="h-10 w-full bg-transparent text-[14px] outline-none placeholder:text-subtle"
            />
          </div>
          <ul
            id={`${id}-list`}
            role="listbox"
            aria-label="Time zones"
            className="max-h-64 overflow-y-auto py-1"
          >
            {found.length === 0 ? (
              <li className="px-3 py-6 text-center text-[13px] text-muted">
                No time zone matches “{query}”.
              </li>
            ) : (
              found.map((zone, index) => (
                <li
                  key={zone.id}
                  role="option"
                  aria-selected={zone.id === shownValue}
                  ref={(element) => {
                    if (index === active) element?.scrollIntoView({ block: "nearest" });
                  }}
                  onMouseEnter={() => setActive(index)}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    pick(zone.id);
                  }}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 px-3 py-2 text-[13.5px]",
                    index === active && "bg-surface-2",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{zone.city}</span>
                    {zone.region && (
                      <span className="block truncate text-[12px] text-subtle">{zone.region}</span>
                    )}
                  </span>
                  <span className="shrink-0 text-[12.5px] text-muted tabular-nums">
                    {zone.offsetLabel}
                  </span>
                  {zone.id === shownValue ? (
                    <Check aria-hidden className="size-4 shrink-0 text-accent" />
                  ) : (
                    <span aria-hidden className="size-4 shrink-0" />
                  )}
                </li>
              ))
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
