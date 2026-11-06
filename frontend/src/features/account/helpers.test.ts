import { describe, expect, it } from "vitest";

import { passwordStrength } from "./helpers";

describe("passwordStrength", () => {
  it("grows with length and never rewards a repeated character", () => {
    expect(passwordStrength("").level).toBe(0);
    expect(passwordStrength("short")).toEqual({ level: 1, label: "Too short" });
    expect(passwordStrength("aaaaaaaaaaaaaaaaaaaaaaa")).toEqual({
      level: 1,
      label: "Too predictable",
    });
    expect(passwordStrength("tenchars!!!").level).toBe(2);
    expect(passwordStrength("correct horse bat").level).toBe(3);
    expect(passwordStrength("correct horse battery staple").level).toBe(4);
  });
});
