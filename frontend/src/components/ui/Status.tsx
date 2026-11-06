import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

export type Tone = "ok" | "warn" | "error" | "neutral" | "accent";

const dotColor: Record<Tone, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  error: "bg-danger",
  neutral: "bg-subtle",
  accent: "bg-accent",
};

/** A colored dot plus a text label: state is never shown by color alone. */
export function StatusLabel({
  tone,
  pulse = false,
  children,
  className,
}: {
  tone: Tone;
  pulse?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[13px] text-fg", className)}>
      <span className="relative flex size-2 shrink-0" aria-hidden>
        {pulse && (
          <span
            className={cn(
              "absolute inline-flex size-full animate-ping rounded-full opacity-50",
              dotColor[tone],
            )}
          />
        )}
        <span className={cn("relative inline-flex size-2 rounded-full", dotColor[tone])} />
      </span>
      {children}
    </span>
  );
}

const badgeTone: Record<Tone, string> = {
  ok: "bg-success-soft text-success",
  warn: "bg-warning-soft text-warning",
  error: "bg-danger-soft text-danger",
  neutral: "bg-surface-2 text-muted ring-1 ring-border ring-inset",
  accent: "bg-accent-soft text-accent",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-full px-2 text-[12px] leading-none font-medium",
        badgeTone[tone],
      )}
    >
      {children}
    </span>
  );
}
