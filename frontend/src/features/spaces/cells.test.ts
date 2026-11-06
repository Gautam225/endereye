import { describe, expect, it } from "vitest";

import { compareValues, formatCell, formatValue, isNumericType } from "./cells";

describe("formatCell", () => {
  it("shows missing values as null, flagged so they can be styled", () => {
    expect(formatCell(null)).toEqual({ text: "null", isNull: true });
    expect(formatCell(undefined)).toEqual({ text: "null", isNull: true });
  });

  it("shows real values exactly as they are", () => {
    expect(formatCell(0)).toEqual({ text: "0", isNull: false });
    expect(formatCell(12345.6789)).toEqual({ text: "12345.6789", isNull: false });
    expect(formatCell("")).toEqual({ text: "", isNull: false });
    expect(formatCell(false)).toEqual({ text: "false", isNull: false });
    expect(formatCell("2025-01-01")).toEqual({ text: "2025-01-01", isNull: false });
  });

  it("writes lists and structures as JSON", () => {
    expect(formatCell([1, 2])).toEqual({ text: "[1,2]", isNull: false });
    expect(formatCell({ a: "x" })).toEqual({ text: '{"a":"x"}', isNull: false });
  });
});

describe("isNumericType", () => {
  it("recognises database number types, in any case", () => {
    for (const type of ["BIGINT", "integer", "DOUBLE", "DECIMAL(10,2)", "UBIGINT", "HUGEINT"]) {
      expect(isNumericType(type)).toBe(true);
    }
  });

  it("does not treat text, dates or flags as numbers", () => {
    for (const type of [
      "VARCHAR",
      "DATE",
      "TIMESTAMP",
      "BOOLEAN",
      "UUID",
      "INTERVAL",
      "INTEGER[]",
      "DECIMAL_X",
    ]) {
      expect(isNumericType(type)).toBe(false);
    }
  });
});

describe("formatValue", () => {
  it("groups numbers in thousands and keeps their decimals", () => {
    expect(formatValue(1234567, "BIGINT")).toEqual({ text: "1,234,567", isNull: false });
    expect(formatValue(22349.05, "DOUBLE")).toEqual({ text: "22,349.05", isNull: false });
    expect(formatValue(0.1 + 0.2, "DOUBLE").text).toBe("0.3"); // float noise is not shown
    expect(formatValue("12345678901234567890", "HUGEINT").text).toBe("12345678901234567890");
  });

  it("shows dates without a midnight time and timestamps without the T", () => {
    expect(formatValue("2025-03-01T00:00:00", "DATE").text).toBe("2025-03-01");
    expect(formatValue("2025-03-01T14:30:05", "TIMESTAMP").text).toBe("2025-03-01 14:30:05");
    expect(formatValue("2025-03-01T14:30:05.120000", "TIMESTAMP").text).toBe(
      "2025-03-01 14:30:05.12",
    );
  });

  it("leaves text and missing values alone", () => {
    expect(formatValue("East", "VARCHAR").text).toBe("East");
    expect(formatValue(null, "DOUBLE")).toEqual({ text: "null", isNull: true });
    expect(formatValue("1234", "VARCHAR").text).toBe("1234"); // text that looks like a number
  });
});

describe("compareValues", () => {
  it("sorts numbers by value, text naturally, and empty values last", () => {
    expect([10, 9, 100].sort((a, b) => compareValues(a, b, "BIGINT"))).toEqual([9, 10, 100]);
    expect(["file10", "file9", "File2"].sort((a, b) => compareValues(a, b, "VARCHAR"))).toEqual([
      "File2",
      "file9",
      "file10",
    ]);
    expect(compareValues(null, 5, "BIGINT")).toBeGreaterThan(0);
    expect(compareValues(5, null, "BIGINT")).toBeLessThan(0);
    expect(compareValues(null, null, "BIGINT")).toBe(0);
  });
});
