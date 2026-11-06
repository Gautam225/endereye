import { describe, expect, it } from "vitest";

import {
  DEFAULT_WIDTH,
  MAX_WIDTH,
  MIN_WIDTH,
  clampWidth,
  getSidebar,
  parseSidebar,
  resetSidebarWidth,
  setSidebarWidth,
} from "./sidebar";

describe("the width of the chat history", () => {
  it("stays between the narrowest and the widest it may be", () => {
    expect(clampWidth(10)).toBe(MIN_WIDTH);
    expect(clampWidth(9999)).toBe(MAX_WIDTH);
    expect(clampWidth(300.4)).toBe(300);
  });

  it("is read back from what was saved, and the usual width when that is missing or damaged", () => {
    expect(parseSidebar(JSON.stringify({ width: 320 }))).toEqual({ width: 320 });
    expect(parseSidebar(JSON.stringify({ width: 5 }))).toEqual({ width: MIN_WIDTH });
    // an older save that also remembered a folded state still gives its width
    expect(parseSidebar(JSON.stringify({ collapsed: true, width: 300 }))).toEqual({ width: 300 });
    for (const bad of [null, "", "not json", '{"width":"wide"}', "[]", "7"]) {
      expect(parseSidebar(bad)).toEqual({ width: DEFAULT_WIDTH });
    }
  });
});

describe("changing it", () => {
  it("follows the drag, never leaves its limits, and goes back to the usual width", () => {
    setSidebarWidth(400);
    expect(getSidebar()).toEqual({ width: 400 });

    setSidebarWidth(50);
    expect(getSidebar().width).toBe(MIN_WIDTH);
    setSidebarWidth(5000);
    expect(getSidebar().width).toBe(MAX_WIDTH);

    resetSidebarWidth();
    expect(getSidebar().width).toBe(DEFAULT_WIDTH);
  });
});
