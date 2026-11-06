import { Check, ChevronRight, LoaderCircle, Square, TriangleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";

import { ThinkingEye } from "../../components/ThinkingEye";
import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import { milliseconds } from "../../lib/format";
import type { AnswerView } from "./answerView";

/** Whole seconds since `active` became true; 0 when not active. */
function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) return;
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 500);
    return () => {
      clearInterval(timer);
      setSeconds(0);
    };
  }, [active]);
  return active ? seconds : 0;
}

/**
 * The thought process, written on the page with no box around it. While the assistant works an
 * eye looks around and the steps are listed as they happen; afterwards it is one quiet line,
 * "Thought process ›", that a person can open.
 */
export function ThinkingPanel({
  view,
  running,
  onStop,
}: {
  view: AnswerView;
  running: boolean;
  onStop: () => void;
}) {
  // Open while thinking and folded afterwards, unless a person has chosen otherwise.
  const [chosen, setChosen] = useState<boolean | null>(null);
  const open = chosen ?? running;
  const seconds = useElapsed(running);
  const steps = view.thoughts.length;

  if (!running && steps === 0) return null;

  return (
    <div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setChosen(!open)}
          className="-ml-1 flex items-center gap-2 rounded-md px-1 py-1 text-[13px] text-muted transition-colors hover:text-fg"
        >
          <ThinkingEye active={running} className="size-5" />
          <span className={cn("font-medium", running && "text-fg")}>
            {running ? `${view.stageLabel ?? "Thinking"}…` : "Thought process"}
          </span>
          <span className="text-subtle tabular-nums">
            {running ? `${seconds}s` : view.totalMs ? milliseconds(view.totalMs) : null}
          </span>
          <ChevronRight
            aria-hidden
            className={cn("size-3.5 text-subtle transition-transform", open && "rotate-90")}
          />
        </button>
        {running && (
          <Button size="sm" variant="ghost" className="ml-auto" onClick={onStop}>
            <Square aria-hidden className="size-3 fill-current" />
            Stop
          </Button>
        )}
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ol
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            aria-live="polite"
            className="overflow-hidden"
          >
            <div className="mt-1 ml-[9px] space-y-2 border-l border-border py-1 pl-4">
              {view.thoughts.map((thought, index) => {
                const current = running && index === steps - 1;
                return (
                  <motion.li
                    key={`${index}-${thought.text}`}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.18 }}
                    className="flex items-start gap-2 text-[13px] leading-5"
                  >
                    <span className="mt-0.5 grid size-4 shrink-0 place-items-center">
                      {thought.kind === "note" ? (
                        <TriangleAlert aria-hidden className="size-3.5 text-warning" />
                      ) : current ? (
                        <LoaderCircle aria-hidden className="size-3.5 animate-spin text-accent" />
                      ) : (
                        <Check aria-hidden className="size-3.5 text-subtle" />
                      )}
                    </span>
                    <span
                      className={cn(
                        thought.kind === "note"
                          ? "text-warning"
                          : thought.kind === "plan"
                            ? "text-fg"
                            : "text-muted",
                      )}
                    >
                      {thought.text}
                    </span>
                  </motion.li>
                );
              })}
              {running && steps === 0 && (
                <li className="flex items-center gap-2 text-[13px] text-subtle">
                  <LoaderCircle aria-hidden className="size-3.5 animate-spin text-accent" />
                  Getting started…
                </li>
              )}
            </div>
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}
