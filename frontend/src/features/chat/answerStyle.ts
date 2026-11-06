import { useSyncExternalStore } from "react";

/**
 * How a question is answered: quick (fewer AI calls, the answer written here), standard, or deep
 * (a big request split into analyses that are solved one by one). Remembered in this browser.
 */
export type AnswerStyle = "quick" | "standard" | "deep";

const KEY = "eoe-answer-style";
const STYLES: AnswerStyle[] = ["quick", "standard", "deep"];

function read(): AnswerStyle {
  try {
    const saved = localStorage.getItem(KEY);
    return STYLES.find((style) => style === saved) ?? "standard";
  } catch {
    return "standard";
  }
}

let current = read();
const listeners = new Set<() => void>();

export function getAnswerStyle(): AnswerStyle {
  return current;
}

export function setAnswerStyle(next: AnswerStyle): void {
  current = next;
  try {
    if (next === "standard") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, next);
  } catch {
    // Private mode: the choice just isn't remembered.
  }
  listeners.forEach((listener) => listener());
}

export function useAnswerStyle(): AnswerStyle {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getAnswerStyle,
    () => "standard",
  );
}
