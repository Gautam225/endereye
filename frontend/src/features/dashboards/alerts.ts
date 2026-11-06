import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "../../lib/api";

export type AlertSource = "item" | "metric";
export type Operator = "gt" | "gte" | "lt" | "lte";
export type AlertState = "new" | "ok" | "triggered" | "error";

export interface Alert {
  id: string;
  space_id: string;
  name: string;
  source_type: AlertSource;
  item_id: string | null;
  item_title: string | null;
  value_column: string | null;
  expression_id: string | null;
  expression_name: string | null;
  where_sql: string | null;
  operator: Operator;
  threshold: number;
  interval_minutes: number;
  recipients: string[];
  renotify_hours: number;
  notify_on_recovery: boolean;
  enabled: boolean;
  state: AlertState;
  last_value: number | null;
  last_error: string;
  last_checked_at: string | null;
  last_triggered_at: string | null;
  next_check_at: string | null;
  created_at: string;
}

export interface AlertEvent {
  id: string;
  kind: "triggered" | "recovered" | "error";
  value: number | null;
  message: string;
  emailed_to: string[];
  at: string;
}

export interface AlertInput {
  name: string;
  source_type: AlertSource;
  item_id?: string;
  value_column?: string | null;
  expression_id?: string;
  where_sql?: string | null;
  operator: Operator;
  threshold: number;
  interval_minutes: number;
  recipients: string[];
  renotify_hours: number;
  notify_on_recovery: boolean;
  enabled: boolean;
}

export const OPERATOR_WORDS: Record<Operator, string> = {
  gt: "goes above",
  gte: "reaches at least",
  lt: "goes below",
  lte: "falls to at most",
};

export const INTERVALS = [
  { value: 15, label: "Every 15 minutes" },
  { value: 60, label: "Every hour" },
  { value: 360, label: "Every 6 hours" },
  { value: 1440, label: "Every day" },
];

export const RENOTIFY = [
  { value: 0, label: "Only when it starts" },
  { value: 6, label: "Again after 6 hours" },
  { value: 24, label: "Again after a day" },
  { value: 168, label: "Again after a week" },
];

export const STATE_TEXT: Record<AlertState, string> = {
  new: "Not checked yet",
  ok: "All good",
  triggered: "Triggered",
  error: "Can't be checked",
};

export const STATE_TONE: Record<AlertState, "neutral" | "ok" | "error" | "warn"> = {
  new: "neutral",
  ok: "ok",
  triggered: "error",
  error: "warn",
};

/** "Failed orders: tell me when it goes above 3". */
export function conditionText(alert: Pick<Alert, "operator" | "threshold">): string {
  return `${OPERATOR_WORDS[alert.operator]} ${alert.threshold}`;
}

/** Numbers as people write them: 2.1, 1,250, no long tails. */
export function valueText(value: number | null): string {
  if (value === null) return "no value yet";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(value);
}

export function everyText(minutes: number): string {
  return (
    INTERVALS.find((i) => i.value === minutes)?.label.toLowerCase() ?? `every ${minutes} minutes`
  );
}

// ── Queries ──────────────────────────────────────────────────────────────────

const key = (spaceId: string) => ["spaces", spaceId, "alerts"] as const;

export function useAlerts(spaceId: string) {
  return useQuery({
    queryKey: key(spaceId),
    queryFn: () => apiGet<Alert[]>(`/spaces/${spaceId}/alerts`),
  });
}

export function useAlertEvents(spaceId: string, alertId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...key(spaceId), alertId, "events"],
    queryFn: () => apiGet<AlertEvent[]>(`/spaces/${spaceId}/alerts/${alertId}/events`),
    enabled,
  });
}

function useAlertMutation<TVariables, TResult>(
  spaceId: string,
  run: (variables: TVariables) => Promise<TResult>,
  errorToast?: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    meta: errorToast ? { errorToast } : undefined,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key(spaceId) }),
  });
}

export function useCreateAlert(spaceId: string) {
  return useAlertMutation(spaceId, (input: AlertInput) =>
    apiSend<Alert>("POST", `/spaces/${spaceId}/alerts`, input),
  );
}

export function useUpdateAlert(spaceId: string) {
  return useAlertMutation(
    spaceId,
    ({ id, changes }: { id: string; changes: Partial<AlertInput> }) =>
      apiSend<Alert>("PATCH", `/spaces/${spaceId}/alerts/${id}`, changes),
  );
}

export function useDeleteAlert(spaceId: string) {
  return useAlertMutation(spaceId, (id: string) =>
    apiSend<void>("DELETE", `/spaces/${spaceId}/alerts/${id}`),
  );
}

export function useCheckAlert(spaceId: string) {
  return useAlertMutation(
    spaceId,
    (id: string) => apiSend<Alert>("POST", `/spaces/${spaceId}/alerts/${id}/check`),
    "Could not check the alert",
  );
}
