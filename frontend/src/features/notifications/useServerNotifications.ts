import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useLocation } from "react-router";

import { apiBlob, apiGet } from "../../lib/api";
import { saveBlob } from "../../lib/download";
import {
  isHere,
  toastFromNotification,
  type ServerAction,
  type ServerNotification,
} from "./mapping";
import { toast } from "../../lib/toast";

/** How often the server is asked what happened. Short enough to feel live, light enough to ignore. */
const POLL_MS = 8000;
/** After this many empty answers in a row nothing is going on, so it asks less often. */
const QUIET_AFTER = 8;
const QUIET_POLL_MS = 30_000;

/** Do what a notification's button says. The server only names it; this is the one place that acts. */
async function perform(action: ServerAction): Promise<void> {
  if (action.type === "download") {
    const { blob } = await apiBlob(action.path);
    saveBlob(blob, action.filename);
  }
}

/**
 * While someone is signed in and looking at the app, asks the server every few seconds what has
 * happened for them (a report finished, an alert fired, they were added to a space) and shows
 * each as a toast. Each is handed over once. Nothing is asked while the tab is in the background;
 * coming back asks at once, so what happened meanwhile appears right away.
 */
export function useServerNotifications(): void {
  const { pathname } = useLocation();
  const here = useRef(pathname);
  const shown = useRef(new Set<string>());
  // Answers with nothing in them, in a row: a quiet stretch is polled less often (8 s -> 30 s).
  const empty = useRef(0);

  useEffect(() => {
    here.current = pathname;
    empty.current = 0; // moving around the app: something may be about to happen
  }, [pathname]);

  const waiting = useQuery({
    queryKey: ["notifications", "pending"],
    queryFn: async () => {
      const found = await apiGet<ServerNotification[]>("/notifications/pending");
      empty.current = found.length === 0 ? empty.current + 1 : 0;
      return found;
    },
    refetchInterval: () => (empty.current >= QUIET_AFTER ? QUIET_POLL_MS : POLL_MS),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  });

  useEffect(() => {
    for (const note of waiting.data ?? []) {
      if (shown.current.has(note.id)) continue;
      shown.current.add(note.id);
      // A chat answer is not announced to someone who is reading that very chat.
      if (note.quiet_when_here && isHere(here.current, note.link)) continue;
      toast.show(toastFromNotification(note, perform));
    }
  }, [waiting.data]);
}
