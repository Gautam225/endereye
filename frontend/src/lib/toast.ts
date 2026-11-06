import { useSyncExternalStore } from "react";

/**
 * The pop-ups in the bottom-right corner. Anything can show one with `toast.success(...)` and
 * friends, from a component or not; the viewport draws them.
 *
 * - Good news and information go away by themselves. Warnings and errors stay until closed, so
 *   they are not missed.
 * - Only a few show at once; the rest wait their turn, oldest first, so each one is read.
 * - A toast with the same `id` as one already there replaces it instead of piling up.
 */

export type ToastLevel = "info" | "success" | "warning" | "error";

export interface ToastAction {
  label: string;
  onClick: () => void | Promise<void>;
}

export interface ToastInput {
  title: string;
  body?: string;
  level?: ToastLevel;
  /** A page of the app: clicking the toast goes there. */
  link?: string;
  /** One button, for the thing most worth doing next (Download, Try again). */
  action?: ToastAction;
  /** Milliseconds until it goes away; `null` keeps it until it is closed. */
  duration?: number | null;
  id?: string;
  /** What kind of message this is, so the person's choice to mute that kind is respected. */
  category?: string;
}

export interface ToastItem {
  id: string;
  title: string;
  body: string;
  level: ToastLevel;
  link: string;
  action: ToastAction | null;
  duration: number | null;
  /** Changes when the same toast is shown again, so its timer starts over. */
  shown: number;
}

/** How long each kind stays when the caller does not say. */
export const DEFAULT_DURATION: Record<ToastLevel, number | null> = {
  success: 6000,
  info: 6000,
  warning: null,
  error: null,
};

/** How many are on screen at once. */
export const MAX_VISIBLE = 3;

type Listener = () => void;

let items: ToastItem[] = [];
let sequence = 0;
const listeners = new Set<Listener>();

function emit() {
  for (const listener of listeners) listener();
}

/** Asks whether a category is muted right now. Set by the app from the person's choices. */
let isMuted: (category: string) => boolean = () => false;

function setMuter(muter: ((category: string) => boolean) | null) {
  isMuted = muter ?? (() => false);
}

function show(input: ToastInput): string {
  const level = input.level ?? "info";
  const id = input.id ?? `toast-${++sequence}`;
  // A kind the person turned off is not shown. Anything without a category always is.
  if (input.category && isMuted(input.category)) return id;
  const item: ToastItem = {
    id,
    title: input.title,
    body: input.body ?? "",
    level,
    link: input.link ?? "",
    action: input.action ?? null,
    duration: input.duration === undefined ? DEFAULT_DURATION[level] : input.duration,
    shown: ++sequence,
  };
  const at = items.findIndex((t) => t.id === id);
  items = at === -1 ? [...items, item] : items.map((t, i) => (i === at ? item : t));
  emit();
  return id;
}

function dismiss(id: string) {
  if (!items.some((t) => t.id === id)) return;
  items = items.filter((t) => t.id !== id);
  emit();
}

function clear() {
  if (items.length === 0) return;
  items = [];
  emit();
}

type Shortcut = (title: string, options?: Omit<ToastInput, "title" | "level">) => string;

const shortcut =
  (level: ToastLevel): Shortcut =>
  (title, options) =>
    show({ ...options, title, level });

export const toast = {
  show,
  setMuter,
  dismiss,
  clear,
  info: shortcut("info"),
  success: shortcut("success"),
  warning: shortcut("warning"),
  error: shortcut("error"),
};

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const snapshot = () => items;

/** Every toast right now, for code that is not a component (and for tests). */
export function getToasts(): ToastItem[] {
  return items;
}

/** Every toast, waiting or showing, oldest first. */
export function useToasts(): ToastItem[] {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

/** The first few show; the others wait until there is room. */
export function split(all: ToastItem[]): { visible: ToastItem[]; waiting: number } {
  return { visible: all.slice(0, MAX_VISIBLE), waiting: Math.max(all.length - MAX_VISIBLE, 0) };
}

/** For tests: start from nothing. */
export function resetToasts() {
  items = [];
  sequence = 0;
  emit();
}
