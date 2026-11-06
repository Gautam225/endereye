import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { apiGet, apiSend } from "../../lib/api";
import { toast } from "../../lib/toast";

export interface Category {
  id: string;
  group: string;
  title: string;
  description: string;
  enabled: boolean;
  /** Shown by the browser itself (going offline), so the browser applies the choice. */
  client_only: boolean;
  admin_only: boolean;
}

export interface Preferences {
  /** The master switch. */
  enabled: boolean;
  /** Set while pop-ups are paused for a while. */
  paused_until: string | null;
  categories: Category[];
}

export interface PreferenceChange {
  enabled?: boolean;
  paused_until?: string;
  clear_pause?: boolean;
  categories?: Record<string, boolean>;
}

const KEY = ["notifications", "preferences"] as const;

// ── Rules that need no network, so they can be tested ────────────────────────

export type PauseChoice = "hour" | "four-hours" | "tomorrow";

/** When a pause of this kind ends. "Tomorrow" is 8:00 the next morning, the person's own time. */
export function pauseEnds(choice: PauseChoice, now: Date = new Date()): Date {
  if (choice === "hour") return new Date(now.getTime() + 60 * 60_000);
  if (choice === "four-hours") return new Date(now.getTime() + 4 * 60 * 60_000);
  const next = new Date(now);
  next.setDate(next.getDate() + 1);
  next.setHours(8, 0, 0, 0);
  return next;
}

/** Are pop-ups off right now: switched off, or paused and the time has not come? */
export function isQuiet(prefs: Pick<Preferences, "enabled" | "paused_until">, now = new Date()) {
  if (!prefs.enabled) return true;
  return prefs.paused_until !== null && new Date(prefs.paused_until).getTime() > now.getTime();
}

/** "3:40 PM" today, "tomorrow 8:00 AM", or a date: when a pause ends, in words. */
export function pausedUntilText(until: string, now: Date = new Date()): string {
  const end = new Date(until);
  const time = end.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const sameDay = end.toDateString() === now.toDateString();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (sameDay) return time;
  if (end.toDateString() === tomorrow.toDateString()) return `tomorrow ${time}`;
  return `${end.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${time}`;
}

/** Is this kind of message muted by the person's choices? (For the browser's own messages.) */
export function isCategoryMuted(prefs: Preferences, category: string, now = new Date()): boolean {
  if (isQuiet(prefs, now)) return true;
  return prefs.categories.find((c) => c.id === category)?.enabled === false;
}

/** The preferences with a change applied, to show the result before the server has answered. */
export function applyChange(prefs: Preferences, change: PreferenceChange): Preferences {
  return {
    enabled: change.enabled ?? prefs.enabled,
    paused_until: change.clear_pause ? null : (change.paused_until ?? prefs.paused_until),
    categories: prefs.categories.map((c) =>
      change.categories && c.id in change.categories
        ? { ...c, enabled: change.categories[c.id] ?? c.enabled }
        : c,
    ),
  };
}

// ── Reading and saving ───────────────────────────────────────────────────────

export function usePreferences() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => apiGet<Preferences>("/notifications/preferences"),
    staleTime: 60_000,
  });
}

/** Saves a change the moment it is made, showing the result at once and putting it back if the
 *  server says no. There is no Save button to forget. */
export function useUpdatePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (change: PreferenceChange) =>
      apiSend<Preferences>("PUT", "/notifications/preferences", change),
    onMutate: async (change) => {
      await queryClient.cancelQueries({ queryKey: KEY });
      const before = queryClient.getQueryData<Preferences>(KEY);
      if (before) queryClient.setQueryData(KEY, applyChange(before, change));
      return { before };
    },
    onError: (_error, _change, context) => {
      if (context?.before) queryClient.setQueryData(KEY, context.before);
      toast.error("Your notification settings were not saved", {
        id: "preferences-not-saved",
        body: "Nothing changed. Please try again.",
      });
    },
    onSuccess: (saved) => queryClient.setQueryData(KEY, saved),
  });
}

export function useResetPreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<Preferences>("DELETE", "/notifications/preferences"),
    onSuccess: (saved) => queryClient.setQueryData(KEY, saved),
    meta: { errorToast: "Could not reset your notification settings" },
  });
}

/** Sends a pop-up to yourself, and asks for it at once so it shows up without the usual wait. */
export function useSendTestNotification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<{ sent: boolean }>("POST", "/notifications/test"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications", "pending"] }),
    meta: { errorToast: "Could not send the test" },
  });
}

/**
 * Keeps the browser's own pop-ups (going offline) in line with the person's choices. The ones
 * the server makes are already filtered there.
 */
export function usePreferenceMuting(): void {
  const prefs = usePreferences();
  const latest = useRef<Preferences | undefined>(undefined);

  useEffect(() => {
    latest.current = prefs.data;
  }, [prefs.data]);

  useEffect(() => {
    toast.setMuter((category) =>
      latest.current ? isCategoryMuted(latest.current, category) : false,
    );
    return () => toast.setMuter(null);
  }, []);
}
