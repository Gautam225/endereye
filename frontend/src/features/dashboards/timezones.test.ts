import { describe, expect, it } from "vitest";

import {
  currentName,
  filterZones,
  formatOffset,
  listZones,
  offsetOf,
  type Zone,
} from "./timezones";

const zone = (id: string, offset: number): Zone => ({
  id,
  city: id.split("/").pop()!.replace(/_/g, " "),
  region: id.split("/").slice(0, -1).join("/"),
  offset,
  offsetLabel: formatOffset(offset),
});

describe("formatOffset", () => {
  it("writes the distance from UTC, including half and quarter hours", () => {
    expect(formatOffset(0)).toBe("UTC");
    expect(formatOffset(330)).toBe("UTC+05:30");
    expect(formatOffset(345)).toBe("UTC+05:45");
    expect(formatOffset(-480)).toBe("UTC-08:00");
  });
});

describe("offsetOf", () => {
  it("knows real zones, including ones that are not whole hours, and rejects made-up ones", () => {
    const winter = new Date("2026-01-15T12:00:00Z");
    expect(offsetOf("Asia/Kolkata", winter)).toBe(330);
    expect(offsetOf("Asia/Kathmandu", winter)).toBe(345);
    expect(offsetOf("America/New_York", winter)).toBe(-300);
    expect(offsetOf("UTC", winter)).toBe(0);
    expect(offsetOf("Mars/Base", winter)).toBeNull();
  });

  it("follows daylight saving", () => {
    expect(offsetOf("Europe/London", new Date("2026-07-15T12:00:00Z"))).toBe(60);
    expect(offsetOf("Europe/London", new Date("2026-01-15T12:00:00Z"))).toBe(0);
  });
});

describe("currentName", () => {
  it("replaces an old name with the current one", () => {
    expect(currentName("Asia/Calcutta")).toBe("Asia/Kolkata");
    expect(currentName("Europe/London")).toBe("Europe/London");
  });
});

describe("listZones", () => {
  it("lists real zones west to east, once each, with the current names", () => {
    const zones = listZones(new Date("2026-01-15T12:00:00Z"));
    const ids = zones.map((z) => z.id);
    expect(ids).toContain("Asia/Kolkata");
    expect(ids).not.toContain("Asia/Calcutta");
    expect(new Set(ids).size).toBe(ids.length);
    const offsets = zones.map((z) => z.offset);
    expect(offsets).toEqual([...offsets].sort((a, b) => a - b));
  });
});

describe("filterZones", () => {
  const zones = [
    zone("Asia/Kolkata", 330),
    zone("Asia/Kathmandu", 345),
    zone("America/New_York", -300),
    zone("Europe/London", 0),
  ];

  it("finds a zone by city or by part of its name", () => {
    expect(filterZones(zones, "new york").map((z) => z.id)).toEqual(["America/New_York"]);
    expect(filterZones(zones, "kath").map((z) => z.id)).toEqual(["Asia/Kathmandu"]);
    expect(filterZones(zones, "asia")).toHaveLength(2);
  });

  it("finds zones by their offset", () => {
    expect(filterZones(zones, "+5:30").map((z) => z.id)).toEqual(["Asia/Kolkata"]);
    expect(filterZones(zones, "UTC+05").map((z) => z.id)).toEqual([
      "Asia/Kolkata",
      "Asia/Kathmandu",
    ]);
    expect(filterZones(zones, "-5").map((z) => z.id)).toEqual(["America/New_York"]);
  });

  it("returns everything for an empty search and nothing for no match", () => {
    expect(filterZones(zones, "  ")).toHaveLength(4);
    expect(filterZones(zones, "atlantis")).toEqual([]);
  });
});
