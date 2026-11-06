import { describe, expect, it } from "vitest";

import { conditionText, everyText, valueText } from "./alerts";

describe("conditionText", () => {
  it("says the condition in words", () => {
    expect(conditionText({ operator: "gt", threshold: 3 })).toBe("goes above 3");
    expect(conditionText({ operator: "lte", threshold: 0.5 })).toBe("falls to at most 0.5");
  });
});

describe("valueText", () => {
  it("shows a number without a long tail, or says there is none", () => {
    expect(valueText(2.123456789)).toBe("2.1235");
    expect(valueText(null)).toBe("no value yet");
  });
});

describe("everyText", () => {
  it("names the check interval", () => {
    expect(everyText(60)).toBe("every hour");
    expect(everyText(7)).toBe("every 7 minutes");
  });
});
