import { describe, expect, it } from "vitest";

import { needsReread, pageRanges, pagesText } from "./library";

describe("needsReread", () => {
  it("flags a ready PDF or deck that has no page count yet", () => {
    expect(needsReread({ filename: "Policy.PDF", status: "ready", page_count: null })).toBe(true);
    expect(needsReread({ filename: "plan.pptx", status: "ready", page_count: null })).toBe(true);
  });

  it("leaves documents that already have pages, still reading, failed, or without pages", () => {
    expect(needsReread({ filename: "a.pdf", status: "ready", page_count: 3 })).toBe(false);
    expect(needsReread({ filename: "a.pdf", status: "processing", page_count: null })).toBe(false);
    expect(needsReread({ filename: "a.pdf", status: "failed", page_count: null })).toBe(false);
    expect(needsReread({ filename: "notes.docx", status: "ready", page_count: null })).toBe(false);
    expect(needsReread({ filename: "notes.md", status: "ready", page_count: null })).toBe(false);
  });
});

describe("pageRanges", () => {
  it("joins runs of pages", () => {
    expect(pageRanges([1, 2, 3, 7, 9, 10])).toBe("1–3, 7, 9–10");
    expect(pageRanges([5])).toBe("5");
    expect(pageRanges([3, 1, 2, 2])).toBe("1–3");
    expect(pageRanges([])).toBe("");
  });

  it("says page or pages in a sentence", () => {
    expect(pagesText([4])).toBe("page 4");
    expect(pagesText([4, 5, 6])).toBe("pages 4–6");
  });
});
