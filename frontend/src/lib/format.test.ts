import { describe, expect, it } from "vitest";

import { rowsText } from "./format";

describe("rowsText", () => {
  it("writes a count, with 'about' for a database's estimate", () => {
    expect(rowsText(1)).toBe("1 row");
    expect(rowsText(1234)).toBe("1,234 rows");
    expect(rowsText(22, true)).toBe("about 22 rows");
  });

  it("says the size is not known instead of showing a number", () => {
    expect(rowsText(-1)).toBe("size not known");
    expect(rowsText(-1, true)).toBe("size not known");
  });

  it("does not turn an unknown size into zero", () => {
    expect(rowsText(0)).toBe("0 rows");
    expect(rowsText(-1)).not.toContain("0");
  });
});
