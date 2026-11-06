import { useEffect } from "react";

import { getToasts, toast } from "../../lib/toast";

/** One toast for "offline" and one for "back", so a flickering connection never stacks them. */
export const OFFLINE_ID = "connection-offline";
export const ONLINE_ID = "connection-online";
export const SERVER_DOWN_ID = "server-unreachable";

/**
 * Tells the person when the browser loses its connection, and when it comes back. The warning
 * stays until the connection returns (it is replaced by a short "back online"), so it is never
 * missed and never left behind.
 */
export function useConnectionToasts(): void {
  useEffect(() => {
    const offline = () => {
      toast.dismiss(ONLINE_ID);
      toast.warning("You are offline", {
        id: OFFLINE_ID,
        category: "connection",
        body: "Changes can't be saved and answers can't be made until you are back online.",
      });
    };
    const online = () => {
      const told = getToasts().some((t) => t.id === OFFLINE_ID || t.id === SERVER_DOWN_ID);
      toast.dismiss(OFFLINE_ID);
      toast.dismiss(SERVER_DOWN_ID);
      if (told)
        toast.success("Back online", { id: ONLINE_ID, duration: 3500, category: "connection" });
    };
    window.addEventListener("offline", offline);
    window.addEventListener("online", online);
    if (typeof navigator !== "undefined" && navigator.onLine === false) offline();
    return () => {
      window.removeEventListener("offline", offline);
      window.removeEventListener("online", online);
    };
  }, []);
}
