import { ChevronsUpDown, CircleUserRound, LogOut, Monitor, Moon, Sun } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router";

import { useHealth } from "../features/status/queries";
import { ROLE_LABEL } from "../features/users/roles";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/cn";
import { initials } from "../lib/format";
import { PALETTES } from "../lib/palettes";
import { useTheme, type ThemePreference } from "../lib/theme";
import { SegmentedControl, type SegmentOption } from "./ui/SegmentedControl";
import { StatusLabel } from "./ui/Status";

const MODES: SegmentOption<ThemePreference>[] = [
  { value: "system", label: "System", icon: <Monitor /> },
  { value: "light", label: "Light", icon: <Sun /> },
  { value: "dark", label: "Dark", icon: <Moon /> },
];

/** The menu's backend dot is checked once a minute: the status page has the close-up view. */
const MENU_CHECK_MS = 60_000;
const WIDTH = 272;
const GAP = 8;

type Tone = "ok" | "warn" | "error" | "neutral";

/** Whether the backend is up, for administrators (the same query as the status page). */
function useBackend(): { tone: Tone; text: string } {
  const health = useHealth(MENU_CHECK_MS);
  if (health.isPending) return { tone: "neutral", text: "Checking backend…" };
  if (health.isError) return { tone: "error", text: "Backend offline" };
  return health.data.status === "ok"
    ? { tone: "ok", text: "Backend online" }
    : { tone: "warn", text: "Database problem" };
}

const DOT: Record<Tone, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  error: "bg-danger",
  neutral: "bg-subtle",
};

/** The person's initials in a circle, with a small dot for the backend when an admin is looking. */
function Avatar({ name, size, admin }: { name: string; size: "sm" | "lg"; admin: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative flex shrink-0 items-center justify-center rounded-full bg-accent-soft font-semibold text-accent",
        size === "lg" ? "size-10 text-[14px]" : "size-8 text-[12px]",
      )}
    >
      {initials(name)}
      {admin && <BackendDot />}
    </span>
  );
}

function BackendDot() {
  const { tone, text } = useBackend();
  return (
    <span
      title={text}
      className={cn(
        "absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full ring-2 ring-surface",
        DOT[tone],
      )}
    />
  );
}

function BackendRow() {
  const { tone, text } = useBackend();
  return (
    <div className="flex items-center justify-between gap-3 px-2.5 py-2 text-[12.5px] text-muted">
      <span>Backend</span>
      <StatusLabel tone={tone}>{text.replace("Backend ", "")}</StatusLabel>
    </div>
  );
}

function Divider() {
  return <div role="separator" className="my-1 h-px bg-border" />;
}

const ITEM =
  "flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 text-left text-[13.5px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:bg-surface-2 focus-visible:text-fg focus-visible:outline-none disabled:opacity-50 [&_svg]:size-4";

/**
 * The account at the foot of the main menu: one button with the person's name and role that opens
 * a menu with their profile, how the app looks (mode and color template), whether the backend is
 * up (administrators), their account settings and sign out. In the narrow menu it is just the
 * avatar, and the menu opens beside it.
 */
export function AccountMenu({
  compact = false,
  onNavigate,
}: {
  compact?: boolean;
  onNavigate?: () => void;
}) {
  const { user, logout, hasRole } = useAuth();
  const { preference, setPreference, resolved, palette, setPalette } = useTheme();
  const [open, setOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [place, setPlace] = useState<{ left: number; bottom: number }>();
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const admin = hasRole("admin");

  const position = useCallback(() => {
    const box = trigger.current?.getBoundingClientRect();
    if (!box) return;
    const left = compact ? box.right + GAP : box.left;
    setPlace({
      left: Math.max(GAP, Math.min(left, window.innerWidth - WIDTH - GAP)),
      bottom: compact ? window.innerHeight - box.bottom : window.innerHeight - box.top + GAP,
    });
  }, [compact]);

  useLayoutEffect(() => {
    if (open) position();
  }, [open, position]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: Event) => {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !panel.current?.contains(target)) setOpen(false);
    };
    window.addEventListener("pointerdown", outside);
    window.addEventListener("resize", position);
    return () => {
      window.removeEventListener("pointerdown", outside);
      window.removeEventListener("resize", position);
    };
  }, [open, position]);

  // The first choice is under the keyboard as soon as the menu opens.
  useEffect(() => {
    if (open && place) panel.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
  }, [open, place]);

  if (!user) return null;

  function close(returnFocus = true) {
    setOpen(false);
    if (returnFocus) trigger.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === "Tab") return setOpen(false);
    const items = [...(panel.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    if (at < 0 || !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
          : (at + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items[next]?.focus();
  }

  const label = `${user.full_name} (${ROLE_LABEL[user.role]})`;
  return (
    <>
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={compact ? `Account menu: ${label}` : undefined}
        title={compact ? label : undefined}
        onClick={() => setOpen((now) => !now)}
        className={cn(
          "flex items-center rounded-lg transition-colors hover:bg-surface-2/70 focus-visible:outline-none",
          "focus-visible:ring-2 focus-visible:ring-accent/40",
          open && "bg-surface-2/70",
          compact ? "size-10 justify-center" : "w-full gap-2.5 p-2 text-left",
        )}
      >
        <Avatar name={user.full_name} size="sm" admin={admin} />
        {!compact && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] leading-tight font-medium">
                {user.full_name}
              </span>
              <span className="block truncate text-[12px] text-subtle">
                {ROLE_LABEL[user.role]}
              </span>
            </span>
            <ChevronsUpDown aria-hidden className="size-4 shrink-0 text-subtle" />
          </>
        )}
      </button>
      {open &&
        place &&
        createPortal(
          <div
            ref={panel}
            role="menu"
            aria-label="Account"
            onKeyDown={onKeyDown}
            style={{ position: "fixed", left: place.left, bottom: place.bottom, width: WIDTH }}
            className="z-50 rounded-xl border border-border-strong bg-surface p-1.5 text-fg shadow-card"
          >
            <div className="flex items-center gap-3 px-2.5 py-2.5">
              <Avatar name={user.full_name} size="lg" admin={false} />
              <div className="min-w-0">
                <p className="truncate text-[14px] leading-tight font-semibold">{user.full_name}</p>
                <p className="truncate text-[12.5px] text-subtle">{user.email}</p>
                <span className="mt-1 inline-block rounded-full border border-border px-2 py-px text-[11px] font-medium text-muted">
                  {ROLE_LABEL[user.role]}
                </span>
              </div>
            </div>
            <Divider />
            <Section title="Appearance">
              <SegmentedControl
                label="Mode"
                options={MODES}
                value={preference}
                onChange={setPreference}
                className="w-full [&>button]:flex-1"
              />
              <div className="mt-2.5 flex items-center justify-between gap-3">
                <span className="text-[12.5px] text-muted">Color</span>
                <div
                  role="radiogroup"
                  aria-label="Color template"
                  className="flex items-center gap-2"
                >
                  {PALETTES.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      role="radio"
                      aria-checked={palette === option.id}
                      aria-label={option.name}
                      title={option.name}
                      onClick={() => setPalette(option.id)}
                      className={cn(
                        "flex size-6 items-center justify-center rounded-full border border-border-strong transition-shadow",
                        "focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none",
                        palette === option.id &&
                          "ring-2 ring-accent ring-offset-2 ring-offset-surface",
                      )}
                    >
                      <span
                        aria-hidden
                        data-palette={option.id}
                        data-theme={resolved}
                        className="block size-4 rounded-full bg-accent"
                      />
                    </button>
                  ))}
                </div>
              </div>
            </Section>
            <Divider />
            {admin && (
              <>
                <BackendRow />
                <Divider />
              </>
            )}
            <Link
              to="/account"
              role="menuitem"
              className={ITEM}
              onClick={() => {
                close(false);
                onNavigate?.();
              }}
            >
              <CircleUserRound aria-hidden />
              Account settings
            </Link>
            <button
              type="button"
              role="menuitem"
              disabled={leaving}
              className={cn(ITEM, "hover:text-danger focus-visible:text-danger")}
              onClick={() => {
                setLeaving(true);
                void logout();
              }}
            >
              <LogOut aria-hidden />
              Sign out
            </button>
          </div>,
          document.body,
        )}
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="px-2.5 py-2">
      <p className="mb-2 text-[11px] font-semibold tracking-wide text-subtle uppercase">{title}</p>
      {children}
    </div>
  );
}
