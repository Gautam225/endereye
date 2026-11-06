import { cn } from "../lib/cn";

/**
 * The Eye of Ender mark, looking around and blinking while the assistant works. Still (and a
 * little quieter) when `active` is false.
 */
export function ThinkingEye({
  active = false,
  className,
}: {
  active?: boolean;
  className?: string;
}) {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden className={cn("size-5", className)}>
      <g className={active ? "eye-blink" : undefined}>
        <path
          d="M2.6 12c2.4-4.1 5.5-6.1 9.4-6.1s7 2 9.4 6.1c-2.4 4.1-5.5 6.1-9.4 6.1S5 16.1 2.6 12Z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <g className={active ? "eye-look" : undefined}>
          <circle cx="12" cy="12" r="3.5" fill="var(--accent)" />
          <circle cx="12" cy="12" r="1.35" fill="var(--bg)" />
        </g>
      </g>
    </svg>
  );
}
