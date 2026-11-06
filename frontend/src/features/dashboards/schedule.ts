import type { ReportRun, ReportSchedule } from "./types";

export const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

/** 1 -> "1st", 22 -> "22nd", 11 -> "11th". */
export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

/** 8, 5 -> "08:05". */
export function timeText(hour: number, minute = 0): string {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export function hourText(hour: number): string {
  return timeText(hour, 0);
}

/** "08:30" from a time box -> [8, 30]; null when it is not a time. */
export function parseTime(text: string): [number, number] | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(text.trim());
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  return hour <= 23 && minute <= 59 ? [hour, minute] : null;
}

/** [4, 5] -> "Friday and Saturday"; Monday to Friday -> "weekday"; all seven -> "day". */
export function weekdaysText(days: number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  if (sorted.length === 7) return "day";
  if (sorted.join() === "0,1,2,3,4") return "weekday";
  const names = sorted.map((d) => WEEKDAYS[d] ?? "?");
  if (names.length <= 1) return names[0] ?? "week";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** "Every Monday at 08:00 (Asia/Kolkata)": the schedule in words. */
export function scheduleText(schedule: ReportSchedule): string {
  const at = `${timeText(schedule.hour, schedule.minute)} (${schedule.timezone})`;
  if (schedule.frequency === "daily") return `Every day at ${at}`;
  if (schedule.frequency === "weekly") {
    return `Every ${weekdaysText(schedule.weekdays)} at ${at}`;
  }
  return `On the ${ordinal(schedule.day_of_month)} of every month at ${at}`;
}

/** Email addresses typed with commas, semicolons, spaces or line breaks between them. */
export function parseRecipients(text: string): string[] {
  const found = text
    .split(/[\s,;]+/)
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean);
  return [...new Set(found)];
}

/** Add an address to the typed list, or take it out again. */
export function toggleRecipient(text: string, email: string): string {
  const current = parseRecipients(text);
  const target = email.toLowerCase();
  const next = current.includes(target)
    ? current.filter((e) => e !== target)
    : [...current, target];
  return next.join(", ");
}

/** The time zone of this browser, a good starting point for a new report. */
export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export const RUN_TEXT: Record<ReportRun["status"], string> = {
  running: "Making it…",
  ok: "Done",
  failed: "Failed",
};

export const FORMAT_TEXT = { pdf: "PDF", xlsx: "Excel", both: "PDF and Excel" } as const;
