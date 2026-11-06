import { cn } from "../../lib/cn";

/**
 * An on/off switch. It is a real button with `role="switch"`, so keyboards and screen readers
 * treat it as one. Pass `aria-labelledby` (or a label of your own) so it has a name.
 */
export function Switch({
  id,
  checked,
  onChange,
  disabled = false,
  className,
  ...aria
}: {
  id?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-[22px] w-10 shrink-0 items-center rounded-full border border-transparent transition-colors duration-200",
        "focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-offset-2 focus-visible:ring-offset-surface focus-visible:outline-none",
        checked ? "bg-accent" : "bg-border-strong",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
      {...aria}
    >
      <span
        aria-hidden
        className={cn(
          "pointer-events-none size-4 rounded-full bg-white shadow-sm ring-0 transition-transform duration-200 ease-out",
          checked ? "translate-x-[21px]" : "translate-x-[3px]",
        )}
      />
    </button>
  );
}
