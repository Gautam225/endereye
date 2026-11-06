import { useSyncExternalStore } from "react";

/**
 * The width of the chat history on the left, which the person sets by dragging its edge.
 * Remembered in this browser and shared by everything that draws or resizes it.
 */
export const MIN_WIDTH = 200;
export const MAX_WIDTH = 480;
export const DEFAULT_WIDTH = 272;

const KEY = "eoe-chat-sidebar";

export interface SidebarState {
  width: number;
}

export function clampWidth(width: number): number {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width)));
}

/** What was saved, or the usual width when it is missing or not what we wrote. */
export function parseSidebar(saved: string | null): SidebarState {
  try {
    const value = JSON.parse(saved ?? "null") as Partial<SidebarState> | null;
    return { width: typeof value?.width === "number" ? clampWidth(value.width) : DEFAULT_WIDTH };
  } catch {
    return { width: DEFAULT_WIDTH };
  }
}

function read(): SidebarState {
  try {
    return parseSidebar(localStorage.getItem(KEY));
  } catch {
    return parseSidebar(null);
  }
}

let current = read();
const listeners = new Set<() => void>();

function change(next: SidebarState): void {
  if (next.width === current.width) return;
  current = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Private mode: the width just isn't remembered.
  }
  listeners.forEach((listener) => listener());
}

export const getSidebar = () => current;
export const setSidebarWidth = (width: number) => change({ width: clampWidth(width) });
export const resetSidebarWidth = () => change({ width: DEFAULT_WIDTH });

export function useSidebar(): SidebarState {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => current,
    () => current,
  );
}

const WIDE = "(min-width: 768px)";

/** Whether the screen is wide enough for the history to sit beside the chat. */
export function useWideScreen(): boolean {
  return useSyncExternalStore(
    (listener) => {
      const media = window.matchMedia(WIDE);
      media.addEventListener("change", listener);
      return () => media.removeEventListener("change", listener);
    },
    () => window.matchMedia(WIDE).matches,
    () => true,
  );
}
