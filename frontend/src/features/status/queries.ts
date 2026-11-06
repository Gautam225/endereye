import { useQuery } from "@tanstack/react-query";

import { apiGet } from "../../lib/api";
import type { Health, LlmStatus } from "./types";

export const REFRESH_MS = 10_000;

/** `every` is how often to look again: the status page watches closely, the little dot in the
 * menu only needs to notice a change within a minute. (A page that watches closely speeds up
 * the shared check while it is open.) */
export function useHealth(every: number = REFRESH_MS) {
  return useQuery({
    queryKey: ["health"],
    // 503 still carries a full report ("degraded"), so it is data, not an error.
    queryFn: () => apiGet<Health>("/health", { okStatuses: [503] }),
    refetchInterval: every,
  });
}

export function useLlmStatus() {
  return useQuery({
    queryKey: ["llm-status"],
    queryFn: () => apiGet<LlmStatus>("/admin/llm/status"),
    refetchInterval: REFRESH_MS,
  });
}
