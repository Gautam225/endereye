import {
  Activity,
  Bell,
  Boxes,
  CalendarClock,
  ChartNoAxesColumn,
  Database,
  Mail,
  LayoutDashboard,
  MessageSquare,
  Menu,
  UsersRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useOutlet } from "react-router";

import type { Role } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/cn";
import { usePreferenceMuting } from "../features/notifications/preferences";
import { useServerNotifications } from "../features/notifications/useServerNotifications";
import { BrandMark } from "./BrandMark";
import { FadeSwitch } from "./FadeSwitch";
import { isAlreadyThere, isCurrent, isPlainClick } from "./navigation";
import { AccountMenu } from "./AccountMenu";

const EASE = [0.16, 1, 0.3, 1] as const;

type NavGroup = "work" | "admin";

const GROUPS: Array<{ id: NavGroup; title: string }> = [
  { id: "work", title: "Workspace" },
  { id: "admin", title: "Administration" },
];

// The account (profile, appearance, sign out) is in the menu at the foot of the sidebar.
const NAV: Array<{
  to: string;
  label: string;
  icon: LucideIcon;
  group: NavGroup;
  roles?: Role[];
}> = [
  { to: "/chat", label: "Ask", icon: MessageSquare, group: "work" },
  { to: "/dashboards", label: "Dashboards", icon: LayoutDashboard, group: "work" },
  { to: "/reports", label: "Reports", icon: CalendarClock, group: "work" },
  { to: "/alerts", label: "Alerts", icon: Bell, group: "work" },
  { to: "/email", label: "Email", icon: Mail, group: "work" },
  { to: "/spaces", label: "Spaces", icon: Boxes, group: "work" },
  { to: "/connections", label: "Connections", icon: Database, group: "admin", roles: ["admin"] },
  {
    to: "/monitoring",
    label: "Monitoring",
    icon: ChartNoAxesColumn,
    group: "admin",
    roles: ["admin"],
  },
  { to: "/status", label: "System status", icon: Activity, group: "admin", roles: ["admin"] },
  { to: "/users", label: "Users", icon: UsersRound, group: "admin", roles: ["admin"] },
];

export function AppShell() {
  const { pathname } = useLocation();
  const outlet = useOutlet();
  useServerNotifications();
  usePreferenceMuting();
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  // The chat uses the whole window; every other page has a centred column.
  // "/chat" is only a door that redirects into a chat, so it already gets the chat's layout:
  // otherwise the menu collapses and the page frame changes in the middle of the redirect.
  const fullBleed = /^\/chat\/?$|^\/spaces\/[^/]+\/chat(\/|$)/.test(pathname);
  // Settings and the dashboard-style pages use a wider column, so a large screen isn't left empty.
  const wide =
    /^\/(account|dashboards|reports|alerts)(\/|$)|^\/spaces\/[^/]+(\/(dashboards|reports|alerts))?\/?$/.test(
      pathname,
    );

  return (
    // The chat is exactly as tall as the window and never scrolls the page: its own areas scroll.
    <div className={cn("flex", fullBleed ? "h-dvh overflow-hidden" : "min-h-dvh")}>
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-surface/50 md:flex",
          fullBleed ? "w-16" : "w-60",
        )}
      >
        <Sidebar navId="nav-desktop" compact={fullBleed} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border bg-bg/85 px-4 backdrop-blur md:hidden">
          <Brand />
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            aria-label="Open menu"
            className="flex size-9 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
          >
            <Menu className="size-5" />
          </button>
        </header>

        <main
          className={
            fullBleed
              ? "h-[calc(100dvh-3.5rem)] w-full min-w-0 md:h-dvh"
              : cn(
                  "mx-auto w-full flex-1 px-5 py-8 md:px-10 md:py-12",
                  wide ? "max-w-[88rem]" : "max-w-5xl",
                )
          }
        >
          {/* The old page fades out before the new one fades in, instead of one replacing the other
              in a single frame. `outlet` is held in a variable so the leaving page keeps its own
              content while it fades. */}
          <FadeSwitch
            id={fullBleed ? "chat" : pathname}
            className={fullBleed ? "h-full" : undefined}
            lift={!fullBleed}
          >
            {outlet}
          </FadeSwitch>
        </main>
      </div>

      <MobileMenu open={menuOpen} onClose={closeMenu} />
    </div>
  );
}

/** The mark in a small tile, and the name (and what it is for) beside it. */
function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 ring-1 ring-border">
        <BrandMark className="size-[18px]" />
      </span>
      {!compact && (
        <span className="min-w-0 leading-tight">
          <span className="block text-[14.5px] font-semibold tracking-[-0.01em]">Eye of Ender</span>
          <span className="block text-[11.5px] text-subtle">Ask your data</span>
        </span>
      )}
    </div>
  );
}

function Sidebar({
  navId,
  onNavigate,
  compact = false,
}: {
  navId: string;
  onNavigate?: () => void;
  /** Icons only: used beside the chat, so the conversation list has the room. */
  compact?: boolean;
}) {
  const { hasRole } = useAuth();
  const { pathname } = useLocation();
  const groups = GROUPS.map((group) => ({
    ...group,
    items: NAV.filter((item) => item.group === group.id && (!item.roles || hasRole(...item.roles))),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="flex h-full flex-col">
      <div className={cn("flex h-16 shrink-0 items-center", compact ? "justify-center" : "px-5")}>
        <Link
          to="/"
          aria-label="Eye of Ender, home"
          title={compact ? "Eye of Ender" : undefined}
          onClick={onNavigate}
          className="rounded-lg focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none"
        >
          <Brand compact={compact} />
        </Link>
      </div>
      <nav
        aria-label="Main"
        className={cn("min-h-0 flex-1 overflow-y-auto pt-1 pb-3", compact ? "px-2" : "px-3")}
      >
        {groups.map((group, index) => (
          <div
            key={group.id}
            role="group"
            aria-label={group.title}
            className={cn(index > 0 && "mt-5")}
          >
            {compact ? (
              index > 0 && <div aria-hidden className="mx-2 mb-3 h-px bg-border" />
            ) : (
              <p className="px-2.5 pb-1.5 text-[11px] font-semibold tracking-wide text-subtle uppercase">
                {group.title}
              </p>
            )}
            <ul className="space-y-0.5">
              {group.items.map(({ to, label, icon: Icon }) => {
                const active = isCurrent(to, pathname);
                return (
                  <li key={to}>
                    <Link
                      to={to}
                      onClick={(event) => {
                        // Already on that page: following the link would reload it and ask the
                        // server for everything again, to arrive where you already are.
                        if (isAlreadyThere(to, pathname) && isPlainClick(event))
                          event.preventDefault();
                        onNavigate?.();
                      }}
                      aria-current={active ? "page" : undefined}
                      aria-label={compact ? label : undefined}
                      title={compact ? label : undefined}
                      className={cn(
                        "relative flex h-9 items-center rounded-lg text-[13.5px] font-medium transition-colors duration-150",
                        "focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none",
                        compact ? "justify-center" : "gap-3 px-2.5",
                        active ? "text-fg" : "text-muted hover:bg-surface-2/60 hover:text-fg",
                      )}
                    >
                      {active && (
                        <motion.span
                          layoutId={navId}
                          className="absolute inset-0 rounded-lg bg-surface-2 ring-1 ring-border"
                          transition={{ type: "spring", bounce: 0.15, duration: 0.35 }}
                        >
                          {!compact && (
                            <span className="absolute top-2 bottom-2 left-0 w-0.5 rounded-full bg-accent" />
                          )}
                        </motion.span>
                      )}
                      <Icon
                        aria-hidden
                        className={cn("relative size-[18px] shrink-0", active && "text-accent")}
                      />
                      {!compact && <span className="relative truncate">{label}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className={cn("border-t border-border", compact ? "flex justify-center py-3" : "p-3")}>
        <AccountMenu compact={compact} onNavigate={onNavigate} />
      </div>
    </div>
  );
}

function MobileMenu({ open, onClose }: { open: boolean; onClose: () => void }) {
  const closeButton = useRef<HTMLButtonElement>(null);

  // Move focus into the menu when it opens; Escape closes it.
  useEffect(() => {
    if (!open) return;
    closeButton.current?.focus();
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal aria-label="Menu">
          <motion.div
            className="absolute inset-0 bg-black/40"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          />
          <motion.aside
            className="absolute inset-y-0 left-0 w-72 max-w-[85vw] border-r border-border bg-surface"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ duration: 0.28, ease: EASE }}
          >
            <button
              ref={closeButton}
              type="button"
              onClick={onClose}
              aria-label="Close menu"
              className="absolute top-4 right-3 flex size-8 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
            >
              <X className="size-4" />
            </button>
            <Sidebar navId="nav-mobile" onNavigate={onClose} />
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  );
}
