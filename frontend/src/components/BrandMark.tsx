import { cn } from "../lib/cn";

/** The Eye of Ender mark: an eye outline with a teal iris. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden className={cn("size-6", className)}>
      <path
        d="M2.6 12c2.4-4.1 5.5-6.1 9.4-6.1s7 2 9.4 6.1c-2.4 4.1-5.5 6.1-9.4 6.1S5 16.1 2.6 12Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="12" r="3.5" fill="var(--accent)" />
      <circle cx="12" cy="12" r="1.35" fill="var(--bg)" />
    </svg>
  );
}
