import { describe, expect, it } from "vitest";

import {
  MAX_EXTERNAL_TABLES,
  describeChange,
  filterTables,
  groupBySchema,
  hasChanges,
  refOf,
  roomLeft,
  selectableRefs,
  sizeText,
} from "./externalTables";
import type { ExternalTable, RefreshResult, TableChange } from "./types";

const table = (schema: string, name: string, comment = ""): ExternalTable => ({
  schema,
  name,
  kind: "table",
  comment,
  estimated_rows: null,
  columns: [],
  foreign_keys: [],
  attached_here: false,
});

const tables = [
  table("public", "orders", "Customer orders"),
  table("public", "customers", "One row per customer"),
  table("finance", "invoices"),
];

describe("filterTables", () => {
  it("returns everything for an empty search", () => {
    expect(filterTables(tables, "  ")).toHaveLength(3);
  });

  it("matches the schema, the name and the comment, in any case", () => {
    expect(filterTables(tables, "FINANCE").map(refOf)).toEqual(["finance.invoices"]);
    expect(filterTables(tables, "per customer").map(refOf)).toEqual(["public.customers"]);
    expect(filterTables(tables, "public order").map(refOf)).toEqual(["public.orders"]);
    expect(filterTables(tables, "nothing like this")).toEqual([]);
  });
});

describe("roomLeft", () => {
  it("counts the tables already in the space and those ticked", () => {
    expect(roomLeft(0, 0)).toBe(MAX_EXTERNAL_TABLES);
    expect(roomLeft(40, 5)).toBe(5);
    expect(roomLeft(48, 10)).toBe(0);
  });
});

const change = (over: Partial<TableChange>): TableChange => ({
  name: "customers",
  ref: "public.customers",
  status: "changed",
  added_columns: [],
  removed_columns: [],
  type_changes: [],
  ...over,
});

describe("describeChange", () => {
  it("lists what is new, gone or retyped", () => {
    expect(describeChange(change({ added_columns: ["phone"] }))).toBe("1 new column (phone)");
    expect(
      describeChange(
        change({
          added_columns: ["a", "b"],
          removed_columns: ["tmp"],
          type_changes: [{ column: "name", from_type: "text", to_type: "varchar(50)" }],
        }),
      ),
    ).toBe("2 new columns (a, b) · 1 removed (tmp) · name: text to varchar(50)");
  });

  it("says a missing table stays in the space", () => {
    expect(describeChange(change({ status: "missing" }))).toContain("stays in the space");
  });
});

describe("hasChanges", () => {
  const result = (over: Partial<RefreshResult>): RefreshResult => ({
    applied: false,
    tables: [change({ status: "unchanged" })],
    joins_added: 0,
    joins_removed: 0,
    skipped_foreign_keys: [],
    ...over,
  });

  it("is false when nothing differs", () => {
    expect(hasChanges(result({}))).toBe(false);
  });

  it("is true for a changed or missing table, or a join that would change", () => {
    expect(hasChanges(result({ tables: [change({ status: "changed" })] }))).toBe(true);
    expect(hasChanges(result({ tables: [change({ status: "missing" })] }))).toBe(true);
    expect(hasChanges(result({ joins_added: 1 }))).toBe(true);
    expect(hasChanges(result({ joins_removed: 1 }))).toBe(true);
  });
});

describe("groupBySchema", () => {
  it("groups by schema in alphabetical order and keeps the order within a schema", () => {
    const groups = groupBySchema([
      table("public", "orders"),
      table("finance", "invoices"),
      table("public", "customers"),
    ]);

    expect(groups.map((g) => g.schema)).toEqual(["finance", "public"]);
    expect(groups[1]?.tables.map((t) => t.name)).toEqual(["orders", "customers"]);
  });

  it("is empty for no tables", () => {
    expect(groupBySchema([])).toEqual([]);
  });
});

describe("selectableRefs", () => {
  const shown = [
    table("public", "a"),
    { ...table("public", "b"), attached_here: true },
    table("public", "c"),
    table("public", "d"),
  ];

  it("skips tables that are already in the space or already ticked", () => {
    expect(selectableRefs(shown, new Set(["public.c"]), 1)).toEqual(["public.a", "public.d"]);
  });

  it("stops at the limit", () => {
    expect(selectableRefs(shown, new Set(), MAX_EXTERNAL_TABLES - 1)).toEqual(["public.a"]);
    expect(selectableRefs(shown, new Set(), MAX_EXTERNAL_TABLES)).toEqual([]);
  });
});

describe("sizeText", () => {
  it("writes a short estimate, or says the size is not known", () => {
    expect(sizeText(9)).toBe("~9 rows");
    expect(sizeText(1)).toBe("~1 row");
    expect(sizeText(331603)).toBe("~331.6K rows");
    expect(sizeText(2844047)).toBe("~2.8M rows");
    expect(sizeText(null)).toBe("size not known");
  });
});
