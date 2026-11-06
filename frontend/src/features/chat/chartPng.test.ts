import { describe, expect, it } from "vitest";

import { pngFileName } from "./chartPng";

describe("pngFileName", () => {
  it("makes a plain file name from a chart title", () => {
    expect(pngFileName("Uptime guarantee (%)")).toBe("uptime-guarantee.png");
    expect(pngFileName("Revenue by region — 2025")).toBe("revenue-by-region-2025.png");
  });

  it("falls back to chart when the title has nothing usable", () => {
    expect(pngFileName("")).toBe("chart.png");
    expect(pngFileName("%%%")).toBe("chart.png");
  });

  it("keeps long titles short", () => {
    expect(pngFileName("a".repeat(200)).length).toBeLessThanOrEqual(64);
  });
});
