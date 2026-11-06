import { describe, expect, it } from "vitest";

import { parseEmails } from "./parseEmails";

describe("parseEmails", () => {
  it("splits on commas, semicolons, spaces and new lines, lowercases and drops repeats", () => {
    const { valid, invalid } = parseEmails("Asha@Co.com, ravi@co.com;\nasha@co.com  nina@co.com");
    expect(valid).toEqual(["asha@co.com", "ravi@co.com", "nina@co.com"]);
    expect(invalid).toEqual([]);
  });

  it("reads addresses copied from a mail program", () => {
    expect(parseEmails("Asha Rao <asha@co.com>, Ravi <ravi@co.com>").valid).toEqual([
      "asha@co.com",
      "ravi@co.com",
    ]);
  });

  it("reports what is not an address, so it can be fixed", () => {
    const { valid, invalid } = parseEmails("asha@co.com, ravi, @co.com, x@y");
    expect(valid).toEqual(["asha@co.com"]);
    expect(invalid).toEqual(["ravi", "@co.com", "x@y"]);
  });

  it("is empty for nothing", () => {
    expect(parseEmails("  \n ")).toEqual({ valid: [], invalid: [] });
  });
});
