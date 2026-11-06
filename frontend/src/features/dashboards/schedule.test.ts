import { describe, expect, it } from "vitest";

import {
  ordinal,
  parseRecipients,
  parseTime,
  scheduleText,
  timeText,
  toggleRecipient,
  weekdaysText,
} from "./schedule";

describe("ordinal", () => {
  it("writes the day of the month", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 28].map(ordinal)).toEqual([
      "1st",
      "2nd",
      "3rd",
      "4th",
      "11th",
      "12th",
      "13th",
      "21st",
      "22nd",
      "28th",
    ]);
  });
});

describe("scheduleText", () => {
  it("says when a report runs, in its own time zone", () => {
    const base = { hour: 8, minute: 0, weekdays: [0], day_of_month: 5, timezone: "Asia/Kolkata" };
    expect(scheduleText({ ...base, frequency: "daily" })).toBe("Every day at 08:00 (Asia/Kolkata)");
    expect(scheduleText({ ...base, frequency: "weekly" })).toBe(
      "Every Monday at 08:00 (Asia/Kolkata)",
    );
    expect(scheduleText({ ...base, frequency: "monthly", hour: 17 })).toBe(
      "On the 5th of every month at 17:00 (Asia/Kolkata)",
    );
  });
});

describe("parseRecipients", () => {
  it("splits on commas, semicolons and spaces, and drops repeats", () => {
    expect(parseRecipients("A@x.com, b@x.com;a@x.com\n c@x.com ")).toEqual([
      "a@x.com",
      "b@x.com",
      "c@x.com",
    ]);
    expect(parseRecipients("  ")).toEqual([]);
  });
});

describe("toggleRecipient", () => {
  it("adds an address that is not in the list and removes one that is", () => {
    expect(toggleRecipient("a@x.com", "B@x.com")).toBe("a@x.com, b@x.com");
    expect(toggleRecipient("a@x.com, b@x.com", "A@x.com")).toBe("b@x.com");
    expect(toggleRecipient("", "a@x.com")).toBe("a@x.com");
  });
});

describe("weekdaysText", () => {
  it("names the chosen days in words", () => {
    expect(weekdaysText([0])).toBe("Monday");
    expect(weekdaysText([5, 4])).toBe("Friday and Saturday");
    expect(weekdaysText([0, 2, 4])).toBe("Monday, Wednesday and Friday");
    expect(weekdaysText([0, 1, 2, 3, 4])).toBe("weekday");
    expect(weekdaysText([6, 5, 4, 3, 2, 1, 0])).toBe("day");
  });
});

describe("times", () => {
  it("writes and reads a time to the minute", () => {
    expect(timeText(8, 5)).toBe("08:05");
    expect(parseTime("17:45")).toEqual([17, 45]);
    expect(parseTime("7:30")).toEqual([7, 30]);
    expect(parseTime("24:00")).toBeNull();
    expect(parseTime("12:60")).toBeNull();
    expect(parseTime("")).toBeNull();
  });

  it("puts the minute and several days into the schedule sentence", () => {
    const text = scheduleText({
      frequency: "weekly",
      hour: 9,
      minute: 30,
      weekdays: [4, 5],
      day_of_month: 1,
      timezone: "Europe/London",
    });
    expect(text).toBe("Every Friday and Saturday at 09:30 (Europe/London)");
  });
});
