import type { KeyboardEvent, PointerEvent, RefObject } from "react";

import {
  MAX_WIDTH,
  MIN_WIDTH,
  clampWidth,
  resetSidebarWidth,
  setSidebarWidth,
  useSidebar,
} from "./sidebar";

const STEP = 16;

/**
 * What lets the chat history be made wider or narrower: its right border. Drag it sideways, or use
 * the keyboard (arrow keys, Home and End); a double click goes back to the usual width.
 */
export function SidebarResizer({ aside }: { aside: RefObject<HTMLElement | null> }) {
  const { width } = useSidebar();

  function start(event: PointerEvent<HTMLElement>) {
    event.preventDefault();
    const handle = event.currentTarget;
    try {
      handle.setPointerCapture(event.pointerId); // keeps the drag going outside the handle
    } catch {
      // Not an active pointer (a pen or a test): the drag still follows the moves below.
    }
    const panel = aside.current;
    const left = panel?.getBoundingClientRect().left ?? 0;
    panel?.setAttribute("data-dragging", "true");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    let latest = clampWidth(width);
    let frame = 0;
    // While dragging only the panel's own width changes (once per frame): the chat is not drawn
    // again for every pixel. The width is saved, and the page told, when the drag ends.
    const move = (moved: globalThis.PointerEvent) => {
      latest = clampWidth(moved.clientX - left);
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        panel?.style.setProperty("--sidebar-width", `${latest}px`);
      });
    };
    const stop = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
      if (frame) cancelAnimationFrame(frame);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      setSidebarWidth(latest);
      panel?.removeAttribute("data-dragging");
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    const step = event.shiftKey ? STEP * 3 : STEP;
    const next =
      event.key === "ArrowRight"
        ? width + step
        : event.key === "ArrowLeft"
          ? width - step
          : event.key === "Home"
            ? MIN_WIDTH
            : event.key === "End"
              ? MAX_WIDTH
              : null;
    if (next === null) return;
    event.preventDefault();
    setSidebarWidth(next);
  }

  return (
    // The whole border: a wide strip that shows a line when the pointer is on it.
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the chat history"
      aria-valuemin={MIN_WIDTH}
      aria-valuemax={MAX_WIDTH}
      aria-valuenow={width}
      tabIndex={0}
      title="Drag to make the chat history wider or narrower (double-click to reset)"
      onPointerDown={start}
      onDoubleClick={resetSidebarWidth}
      onKeyDown={onKeyDown}
      className="group absolute top-0 -right-1.5 z-20 hidden h-full w-3 cursor-col-resize touch-none focus-visible:outline-none md:block"
    >
      <span className="mx-auto block h-full w-0.5 rounded-full bg-transparent transition-colors group-hover:bg-accent/50 group-focus-visible:bg-accent/50 group-active:bg-accent" />
    </div>
  );
}
