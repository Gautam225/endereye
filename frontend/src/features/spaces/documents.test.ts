import { describe, expect, it } from "vitest";

import { documentsPollInterval } from "./documents";

describe("documentsPollInterval", () => {
  it("polls only while a document is still being read", () => {
    expect(documentsPollInterval([{ status: "ready" }, { status: "processing" }])).toBe(1500);
    expect(documentsPollInterval([{ status: "ready" }, { status: "failed" }])).toBe(false);
    expect(documentsPollInterval([])).toBe(false);
    expect(documentsPollInterval(undefined)).toBe(false);
  });
});
