/**
 * Real time zones to choose from, each with its current offset from UTC, so people can pick by
 * city or by offset ("+05:30") instead of guessing a name. The names are the IANA names the
 * server understands (Asia/Kolkata, Europe/London, America/New_York).
 */

export interface Zone {
  id: string;
  /** "Kolkata", "New York": the last part of the name, spaces for underscores. */
  city: string;
  /** "Asia", "America/Argentina": everything before it. */
  region: string;
  /** Minutes east of UTC right now (daylight saving included). */
  offset: number;
  /** "UTC+05:30". */
  offsetLabel: string;
}

/** Old names some browsers still report, and the current name for each. */
const CURRENT_NAME: Record<string, string> = {
  "Asia/Calcutta": "Asia/Kolkata",
  "Asia/Saigon": "Asia/Ho_Chi_Minh",
  "Asia/Katmandu": "Asia/Kathmandu",
  "Asia/Rangoon": "Asia/Yangon",
  "Europe/Kiev": "Europe/Kyiv",
  "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
  "Pacific/Truk": "Pacific/Chuuk",
};

export function currentName(id: string): string {
  return CURRENT_NAME[id] ?? id;
}

/** 330 -> "UTC+05:30", -480 -> "UTC-08:00", 0 -> "UTC". */
export function formatOffset(minutes: number): string {
  if (minutes === 0) return "UTC";
  const sign = minutes < 0 ? "-" : "+";
  const abs = Math.abs(minutes);
  return `UTC${sign}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}

/** The offset of a zone at a moment, in minutes east of UTC, or null when the zone is unknown. */
export function offsetOf(id: string, at: Date = new Date()): number | null {
  try {
    const part = new Intl.DateTimeFormat("en-US", { timeZone: id, timeZoneName: "longOffset" })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName")?.value;
    if (part === undefined) return null;
    if (part === "GMT") return 0;
    const match = /^GMT([+-])(\d{1,2})(?::(\d{2}))?$/.exec(part);
    if (!match) return null;
    const minutes = Number(match[2]) * 60 + Number(match[3] ?? 0);
    return match[1] === "-" ? -minutes : minutes;
  } catch {
    return null;
  }
}

function describe(id: string, at: Date): Zone | null {
  const offset = offsetOf(id, at);
  if (offset === null) return null;
  const parts = id.split("/");
  return {
    id,
    city: (parts[parts.length - 1] ?? id).replace(/_/g, " "),
    region: parts.slice(0, -1).join("/").replace(/_/g, " "),
    offset,
    offsetLabel: formatOffset(offset),
  };
}

const FALLBACK = [
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Africa/Cairo",
  "Africa/Johannesburg",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Dhaka",
  "Asia/Bangkok",
  "Asia/Singapore",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Pacific/Auckland",
  "America/Sao_Paulo",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
];

/** Every zone this browser knows, ordered from west to east and then by name. */
export function listZones(at: Date = new Date()): Zone[] {
  let ids: string[];
  try {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    ids = intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    ids = [];
  }
  const names = new Set([...(ids.length > 0 ? ids : FALLBACK), "UTC"].map(currentName));
  const zones = [...names].flatMap((id) => {
    const zone = describe(id, at);
    return zone ? [zone] : [];
  });
  return zones.sort((a, b) => a.offset - b.offset || a.id.localeCompare(b.id));
}

/** Zones matching what was typed: a city, a country-side name, an offset ("+5:30", "ist" not). */
export function filterZones(zones: Zone[], query: string): Zone[] {
  const text = query.trim().toLowerCase();
  if (text === "") return zones;
  const offset = text.replace(/^utc|^gmt/, "").replace(/\s/g, "");
  const wantsOffset = /^[+-]\d{1,2}(:\d{2})?$/.test(offset);
  return zones.filter((zone) => {
    if (zone.id.toLowerCase().replace(/_/g, " ").includes(text)) return true;
    if (!wantsOffset) return false;
    const label = zone.offsetLabel.replace("UTC", "");
    const padded = offset.replace(/^([+-])(\d):/, "$10$2:").replace(/^([+-])(\d)$/, "$10$2");
    return label.startsWith(padded);
  });
}
