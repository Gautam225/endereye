import { describe, expect, it } from "vitest";

import { fileSize } from "../../lib/format";
import { suggestTableName } from "./names";

describe("suggestTableName", () => {
  it("matches the backend's rule", () => {
    expect(suggestTableName("Sales 2026 (final).csv")).toBe("sales_2026_final");
    expect(suggestTableName("2025-orders.xlsx")).toBe("t_2025_orders");
    expect(suggestTableName("orders_delta")).toBe("orders_delta");
    expect(suggestTableName("((()).csv")).toBe("table");
  });
});

describe("fileSize", () => {
  it("picks a readable unit", () => {
    expect(fileSize(512)).toBe("512 B");
    expect(fileSize(2048)).toBe("2 KB");
    expect(fileSize(5_400_000)).toBe("5.1 MB");
    expect(fileSize(300 * 1024 * 1024)).toBe("300 MB");
  });
});
