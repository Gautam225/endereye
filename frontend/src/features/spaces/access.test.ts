import { describe, expect, it } from "vitest";

import { draftProblem, ruleText, whoText } from "./access";

describe("what a rule says", () => {
  it("reads each kind in one line", () => {
    expect(
      ruleText({ kind: "hide_column", table: "sales", column: "unit_price", expression: null }),
    ).toBe("Hide unit_price of sales");
    expect(
      ruleText({ kind: "mask_column", table: "people", column: "email", expression: null }),
    ).toBe("Show email of people as empty");
    expect(
      ruleText({ kind: "row_filter", table: "sales", column: null, expression: "region = 'West'" }),
    ).toBe("Only the rows of sales where region = 'West'");
  });

  it("names who it is for: a person by email, else the audience", () => {
    expect(whoText({ audience: "viewers", user_id: "u1", user_email: "vera@example.com" })).toBe(
      "vera@example.com",
    );
    expect(whoText({ audience: "members", user_id: null, user_email: null })).toBe(
      "Viewers and editors (not admins)",
    );
    expect(whoText({ audience: "everyone", user_id: null, user_email: null })).toBe(
      "Everyone, admins too",
    );
  });
});

describe("a rule that can be sent", () => {
  it("needs a table, then the piece its kind needs, then a person when it is for one", () => {
    expect(draftProblem({ kind: "hide_column", audience: "viewers" }, "audience")).toBe(
      "Choose a table.",
    );
    expect(
      draftProblem({ table_id: "t", kind: "hide_column", audience: "viewers" }, "audience"),
    ).toBe("Choose a column.");
    expect(
      draftProblem(
        { table_id: "t", kind: "row_filter", expression: "  ", audience: "viewers" },
        "audience",
      ),
    ).toBe("Write the condition the rows must meet.");
    expect(
      draftProblem(
        { table_id: "t", kind: "mask_column", column: "email", audience: "viewers" },
        "person",
      ),
    ).toBe("Choose a person.");
    expect(
      draftProblem(
        { table_id: "t", kind: "mask_column", column: "email", audience: "viewers" },
        "audience",
      ),
    ).toBeNull();
  });
});
