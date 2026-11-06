import { AnimatePresence, motion, type PanInfo } from "motion/react";
import {
  ArrowRight,
  CircleAlert,
  CircleCheck,
  Info,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";

import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import { split, toast, useToasts, type ToastItem, type ToastLevel } from "../../lib/toast";

const LOOK: Record<ToastLevel, { icon: LucideIcon; strip: string; circle: string; bar: string }> = {
  success: {
    icon: CircleCheck,
    strip: "bg-success",
    circle: "bg-success-soft text-success",
    bar: "bg-success",
  },
  info: { icon: Info, strip: "bg-accent", circle: "bg-accent-soft text-accent", bar: "bg-accent" },
  warning: {
    icon: TriangleAlert,
    strip: "bg-warning",
    circle: "bg-warning-soft text-warning",
    bar: "bg-warning",
  },
  error: {
    icon: CircleAlert,
    strip: "bg-danger",
    circle: "bg-danger-soft text-danger",
    bar: "bg-danger",
  },
};

const SWIPE_TO_CLOSE = 90; // pixels to the right that dismiss a toast

/**
 * Draws the pop-ups in the bottom-right corner. They slide in from the right with a soft spring,
 * the others glide up to make room, and one leaves by sliding out (or by being swiped away). A
 * thin bar counts down the ones that go by themselves, and stops while you hold the mouse over
 * one or focus it. Clicking a toast goes to the page it is about.
 */
export function ToastViewport() {
  const all = useToasts();
  const { visible, waiting } = split(all);

  return (
    <div
      role="region"
      aria-label="Notifications"
      className="pointer-events-none fixed inset-x-3 bottom-3 z-[60] flex flex-col items-end gap-2.5 sm:inset-x-auto sm:right-5 sm:bottom-5"
    >
      <AnimatePresence initial={false}>
        {visible.map((item) => (
          <ToastCard key={item.id} item={item} />
        ))}
      </AnimatePresence>
      <AnimatePresence initial={false}>
        {waiting > 0 && (
          <motion.div
            key="waiting"
            layout
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.18 }}
            className="pointer-events-auto flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 text-[12.5px] text-muted shadow-lg"
          >
            {waiting} more waiting
            <button
              type="button"
              onClick={toast.clear}
              className="font-medium text-accent underline-offset-2 hover:underline"
            >
              Dismiss all
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function ToastCard({ item }: { item: ToastItem }) {
  const navigate = useNavigate();
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(false);

  // A toast that goes by itself is closed by a timer, not by the end of the countdown bar: a
  // person who asked their computer for less motion has every CSS animation cut to nothing, and
  // the toast would vanish the moment it appeared. The timer stops while it is hovered or focused
  // and carries on with the time that was left.
  const left = useRef(item.duration ?? 0);
  useEffect(() => {
    left.current = item.duration ?? 0;
  }, [item.shown, item.duration]);
  useEffect(() => {
    if (item.duration === null || paused) return;
    const started = Date.now();
    const timer = setTimeout(() => toast.dismiss(item.id), Math.max(left.current, 0));
    return () => {
      clearTimeout(timer);
      left.current -= Date.now() - started;
    };
  }, [paused, item.shown, item.duration, item.id]);
  const look = LOOK[item.level];
  const Icon = look.icon;
  const goes = item.link !== "";

  function open() {
    toast.dismiss(item.id);
    if (goes) navigate(item.link);
  }

  async function run() {
    if (!item.action || busy) return;
    setBusy(true);
    try {
      await item.action.onClick();
      toast.dismiss(item.id);
    } catch {
      setBusy(false);
      toast.error("That did not work", { id: `${item.id}-action`, body: "Please try again." });
    }
  }

  function onDragEnd(_: unknown, info: PanInfo) {
    if (info.offset.x > SWIPE_TO_CLOSE || info.velocity.x > 600) toast.dismiss(item.id);
  }

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      toast.dismiss(item.id);
    }
  }

  return (
    <motion.div
      layout
      role={item.level === "error" ? "alert" : "status"}
      initial={{ opacity: 0, x: 72, scale: 0.94 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 72, scale: 0.94, transition: { duration: 0.18, ease: "easeIn" } }}
      transition={{ type: "spring", stiffness: 380, damping: 32, mass: 0.9 }}
      drag="x"
      dragConstraints={{ left: 0, right: 0 }}
      dragElastic={{ left: 0.04, right: 0.7 }}
      onDragEnd={onDragEnd}
      whileDrag={{ cursor: "grabbing" }}
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={() => setPaused(false)}
      onKeyDown={onKeyDown}
      className="pointer-events-auto relative w-full touch-pan-y overflow-hidden rounded-xl border border-border bg-surface shadow-[0_10px_30px_-8px_rgb(0_0_0/0.35)] sm:w-[23rem]"
    >
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1", look.strip)} />
      <div className="flex gap-3 py-3.5 pr-2.5 pl-4.5">
        <span
          aria-hidden
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-full",
            look.circle,
          )}
        >
          <Icon className="size-[18px]" />
        </span>

        <div className="min-w-0 flex-1">
          {goes ? (
            <button
              type="button"
              onClick={open}
              className="group block w-full rounded-md text-left focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none"
            >
              <Text item={item} arrow />
            </button>
          ) : (
            <Text item={item} />
          )}
          {item.action && (
            <div className="mt-2.5">
              <Button size="sm" onClick={() => void run()} loading={busy}>
                {item.action.label}
              </Button>
            </div>
          )}
        </div>

        <button
          type="button"
          aria-label="Dismiss notification"
          onClick={() => toast.dismiss(item.id)}
          className="-mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md text-subtle transition-colors hover:bg-surface-2 hover:text-fg focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none"
        >
          <X aria-hidden className="size-4" />
        </button>
      </div>

      {item.duration !== null && (
        <span
          key={item.shown}
          aria-hidden
          className={cn("toast-countdown absolute inset-x-0 bottom-0 h-0.5 opacity-60", look.bar)}
          style={
            {
              "--toast-ms": `${item.duration}ms`,
              animationPlayState: paused ? "paused" : "running",
            } as CSSProperties
          }
        />
      )}
    </motion.div>
  );
}

function Text({ item, arrow = false }: { item: ToastItem; arrow?: boolean }) {
  return (
    <>
      <span className="flex items-start gap-1.5">
        <span className="text-[14px] leading-5 font-semibold">{item.title}</span>
        {arrow && (
          <ArrowRight
            aria-hidden
            className="mt-1 size-3.5 shrink-0 text-subtle opacity-0 transition-all group-hover:translate-x-0.5 group-hover:opacity-100 group-focus-visible:opacity-100"
          />
        )}
      </span>
      {item.body && (
        <span className="mt-0.5 line-clamp-3 block text-[13px] leading-[1.35rem] text-muted">
          {item.body}
        </span>
      )}
    </>
  );
}
