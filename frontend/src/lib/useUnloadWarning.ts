import { useEffect } from "react";

/**
 * While `active`, the browser asks before the page is refreshed or closed. A file that is still
 * being sent would be cut off by that, and there is no way to continue it afterwards.
 */
export function useUnloadWarning(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [active]);
}
