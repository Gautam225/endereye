import { describe, expect, it } from "vitest";

import { columnChange, parseSynonyms } from "./metadata";
import type { ColumnMeta } from "./types";

const column: ColumnMeta = {
  id: "1",
  name: "region",
  type: "VARCHAR",
  position: 0,
  description: "Sales region",
  synonyms: ["state"],
  hidden: false,
  share_values: true,
  entity_matching: true,
  indexed_values: 2,
  stats: null,
};

describe("parseSynonyms", () => {
  it("trims, drops blanks and repeats, and keeps the order", () => {
    expect(parseSynonyms(" state , Zone ,STATE,, zone  area ")).toEqual([
      "state",
      "Zone",
      "zone area",
    ]);
  });
});

describe("columnChange", () => {
  it("is empty when nothing differs, even in spacing", () => {
    expect(columnChange(column, { description: " Sales region ", synonyms: "state" })).toEqual({});
    expect(columnChange(column, undefined)).toEqual({});
  });

  it("lists only what changed", () => {
    expect(columnChange(column, { description: "Region", synonyms: "state" })).toEqual({
      description: "Region",
    });
    expect(columnChange(column, { description: "Sales region", synonyms: "state, zone" })).toEqual({
      synonyms: ["state", "zone"],
    });
  });
});
