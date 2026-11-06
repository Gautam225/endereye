import type { ReactNode } from "react";

/** A command or file name inside a sentence. */
export function InlineCode({ children }: { children: ReactNode }) {
  return (
    // box-decoration-clone: when a long command wraps, each line gets its own complete box.
    <code className="rounded bg-surface-2 box-decoration-clone px-1.5 py-0.5 font-mono text-[12.5px] break-words text-fg ring-1 ring-border ring-inset">
      {children}
    </code>
  );
}
