import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

const VALUE_TONE = {
  default: "text-fg",
  ok: "text-success",
  warn: "text-warning",
  danger: "text-danger",
} as const;

/** One figure with its name, for rows of numbers (monitoring, system status). */
export function StatTile({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: LucideIcon;
  /** Colors the figure when it is good or bad news; the words around it say so too. */
  tone?: keyof typeof VALUE_TONE;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[12px] font-medium tracking-wide text-subtle uppercase">{label}</p>
        {Icon && (
          <span
            aria-hidden
            className="flex size-7 shrink-0 items-center justify-center rounded-md bg-surface-2 text-muted [&_svg]:size-4"
          >
            <Icon />
          </span>
        )}
      </div>
      <p
        className={cn(
          "mt-2.5 text-[26px] leading-none font-semibold tracking-[-0.01em] tabular-nums",
          VALUE_TONE[tone],
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-2.5 text-[12.5px] leading-snug text-subtle">{hint}</p>}
    </div>
  );
}
