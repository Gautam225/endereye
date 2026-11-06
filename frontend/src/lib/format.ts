const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "just now", "3 minutes ago", "2 hours ago" */
export function timeAgo(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "never";
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return "just now";
  if (abs < 3600) return relative.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return relative.format(Math.round(seconds / 3600), "hour");
  return relative.format(Math.round(seconds / 86400), "day");
}

/** 45 -> "45 s", 300 -> "5 min", 7200 -> "2 h" */
export function shortDuration(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} s`;
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

/** 840 -> "840 ms", 1830 -> "1.8 s" */
export function milliseconds(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export const providerLabel: Record<string, string> = {
  openrouter: "OpenRouter",
  groq: "Groq",
};

/** "Asha Admin" -> "AA" */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

const integer = new Intl.NumberFormat("en");

/** 1234567 -> "1,234,567" */
export function count(n: number): string {
  return integer.format(n);
}

const compactInteger = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** 331603 -> "331.6K", 2844047 -> "2.8M", 950 -> "950" */
export function compactCount(n: number): string {
  return compactInteger.format(n);
}

/** "3 rows", "1 row" */
export function plural(n: number, word: string): string {
  return `${count(n)} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * How many rows a table has. A size of -1 means it is not known (a table of a database that has
 * not been analysed), which is said so rather than shown as a number. `approximate` marks a
 * database's estimate.
 */
export function rowsText(rows: number, approximate = false): string {
  if (rows < 0) return "size not known";
  return `${approximate ? "about " : ""}${plural(rows, "row")}`;
}

/** 2048 -> "2 KB", 5_400_000 -> "5.1 MB" */
export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value < 10 ? value.toFixed(1).replace(/\.0$/, "") : Math.round(value)} ${units[unit]}`;
}
