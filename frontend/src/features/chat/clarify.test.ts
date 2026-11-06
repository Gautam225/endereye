import { describe, expect, it } from "vitest";

import { composeReply, toggleChoice } from "./clarify";

const offered = ["Total dietitians", "Dietitians with an appointment", "Active dietitians"];

describe("toggleChoice", () => {
  it("ticks and unticks, keeping the order the answers were offered in", () => {
    let selected: string[] = [];
    selected = toggleChoice(selected, "Active dietitians", offered);
    selected = toggleChoice(selected, "Total dietitians", offered);

    expect(selected).toEqual(["Total dietitians", "Active dietitians"]);
    expect(toggleChoice(selected, "Total dietitians", offered)).toEqual(["Active dietitians"]);
  });

  it("ignores something that was never offered", () => {
    expect(toggleChoice([], "Something else", offered)).toEqual([]);
  });
});

describe("composeReply", () => {
  it("sends what was typed when nothing was picked", () => {
    expect(composeReply([], "  the active ones only  ")).toBe("the active ones only");
  });

  it("sends the picked answer, or answers joined with a semicolon", () => {
    expect(composeReply(["Total dietitians"], "")).toBe("Total dietitians");
    expect(composeReply(["Total dietitians", "Active dietitians"], "")).toBe(
      "Total dietitians; Active dietitians",
    );
  });

  it("puts what was typed after the picked answer as a second sentence", () => {
    expect(composeReply(["Total dietitians"], "only for 2025")).toBe(
      "Total dietitians. Only for 2025",
    );
    expect(composeReply(["Total dietitians?"], "by city")).toBe("Total dietitians? By city");
  });

  it("is empty when there is nothing to send", () => {
    expect(composeReply([], "   ")).toBe("");
    expect(composeReply([" "], "")).toBe("");
  });
});
