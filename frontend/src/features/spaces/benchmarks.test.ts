import { describe, expect, it } from "vitest";

import {
  accuracyText,
  changeText,
  isActive,
  pollInterval,
  progressOf,
  scoreText,
  trendPoints,
} from "./benchmarks";

describe("accuracyText", () => {
  it("shows a percentage, or says there is no score yet", () => {
    expect(accuracyText(0.75)).toBe("75%");
    expect(accuracyText(1)).toBe("100%");
    expect(accuracyText(0)).toBe("0%");
    expect(accuracyText(0.3333)).toBe("33%");
    expect(accuracyText(null)).toBe("No score yet");
  });
});

describe("scoreText", () => {
  it("counts only the questions that could be judged", () => {
    expect(scoreText({ correct: 3, done: 5, reference_errors: 1 })).toBe("3 of 4 correct");
    expect(scoreText({ correct: 0, done: 0, reference_errors: 0 })).toBe("Nothing judged yet");
    expect(scoreText({ correct: 0, done: 2, reference_errors: 2 })).toBe("Nothing judged yet");
  });
});

describe("polling", () => {
  it("asks again only while a run is going", () => {
    expect(pollInterval({ status: "running" })).toBe(1500);
    expect(pollInterval({ status: "finished" })).toBe(false);
    expect(pollInterval({ status: "failed" })).toBe(false);
    expect(pollInterval(undefined)).toBe(false);
    expect(isActive({ status: "running" })).toBe(true);
    expect(isActive(undefined)).toBe(false);
  });
});

describe("progressOf", () => {
  it("is the share done, never above one", () => {
    expect(progressOf({ done: 1, total: 4 })).toBe(0.25);
    expect(progressOf({ done: 5, total: 4 })).toBe(1);
    expect(progressOf({ done: 0, total: 0 })).toBe(0);
  });
});

describe("changeText", () => {
  it("shows the change in percentage points", () => {
    expect(changeText(0.8, 0.75)).toBe("+5 pts");
    expect(changeText(0.5, 0.75)).toBe("-25 pts");
    expect(changeText(0.5, 0.5)).toBe("no change");
    expect(changeText(null, 0.5)).toBeNull();
  });
});

describe("trendPoints", () => {
  it("draws high scores near the top and skips runs with no score", () => {
    expect(trendPoints([1, 0], 100, 40)).toBe("0.0,0.0 100.0,40.0");
    expect(trendPoints([0.5, null, 1], 100, 40)).toBe("0.0,20.0 100.0,0.0");
    expect(trendPoints([], 100, 40)).toBe("");
    expect(trendPoints([0.5], 100, 40)).toBe("50.0,20.0");
  });
});
