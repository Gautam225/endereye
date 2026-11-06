import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiBlob, apiGet, apiSend } from "../../lib/api";
import { toast } from "../../lib/toast";
import type {
  Dashboard,
  KeptItem,
  KeptPage,
  PinInput,
  Report,
  ReportInput,
  ReportOptions,
  ReportRun,
} from "./types";

const dashboardsKey = (spaceId: string) => ["spaces", spaceId, "dashboards"] as const;
const reportsKey = (spaceId: string) => ["spaces", spaceId, "reports"] as const;

// ── Dashboards ───────────────────────────────────────────────────────────────

export function useDashboards(spaceId: string) {
  return useQuery({
    queryKey: dashboardsKey(spaceId),
    queryFn: () => apiGet<Dashboard[]>(`/spaces/${spaceId}/dashboards`),
  });
}

function useDashboardMutation<TVariables, TResult>(
  spaceId: string,
  run: (variables: TVariables) => Promise<TResult>,
  options: { errorToast?: string; after?: (result: TResult) => void } = {},
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    meta: options.errorToast ? { errorToast: options.errorToast } : undefined,
    onSuccess: (result) => {
      options.after?.(result);
      return queryClient.invalidateQueries({ queryKey: dashboardsKey(spaceId) });
    },
  });
}

export function useCreateDashboard(spaceId: string) {
  return useDashboardMutation(spaceId, (name: string) =>
    apiSend<Dashboard>("POST", `/spaces/${spaceId}/dashboards`, { name }),
  );
}

export function useRenameDashboard(spaceId: string) {
  return useDashboardMutation(spaceId, ({ id, name }: { id: string; name: string }) =>
    apiSend<Dashboard>("PATCH", `/spaces/${spaceId}/dashboards/${id}`, { name }),
  );
}

export function useDeleteDashboard(spaceId: string) {
  return useDashboardMutation(spaceId, (id: string) =>
    apiSend<void>("DELETE", `/spaces/${spaceId}/dashboards/${id}`),
  );
}

export function usePinAnswer(spaceId: string) {
  return useDashboardMutation(
    spaceId,
    (input: PinInput) =>
      apiSend<KeptItem>("POST", `/spaces/${spaceId}/dashboards/pin`, {
        conversation_id: input.conversationId,
        message_id: input.messageId,
        dashboard_id: input.dashboardId ?? null,
        title: input.title ?? null,
      }),
    { errorToast: "Could not keep this answer" },
  );
}

export function useRefreshItem(spaceId: string) {
  return useDashboardMutation(
    spaceId,
    (id: string) => apiSend<KeptItem>("POST", `/spaces/${spaceId}/dashboards/items/${id}/refresh`),
    {
      errorToast: "Could not refresh",
      // The tile shows the new numbers on its own; only a failure needs saying.
      after: (item) => {
        if (item.refresh_error) {
          toast.error(`“${item.title}” could not be refreshed`, {
            id: `refresh:${item.id}`,
            body: `${item.refresh_error} The old result is still shown.`,
          });
        }
      },
    },
  );
}

export function useRefreshDashboard(spaceId: string) {
  return useDashboardMutation(
    spaceId,
    (id: string) => apiSend<KeptItem[]>("POST", `/spaces/${spaceId}/dashboards/${id}/refresh`),
    {
      errorToast: "Could not refresh the dashboard",
      after: (items) => {
        const failed = items.filter((item) => item.refresh_error);
        if (items.length === 0) return;
        if (failed.length === 0) {
          toast.success(`Refreshed ${items.length} ${items.length === 1 ? "answer" : "answers"}`, {
            id: "dashboard-refreshed",
          });
        } else {
          toast.error(`${failed.length} of ${items.length} answers could not be refreshed`, {
            id: "dashboard-refreshed",
            body: `${failed.map((i) => i.title).join(", ")}. Their old results are still shown.`,
          });
        }
      },
    },
  );
}

export function useRenameItem(spaceId: string) {
  return useDashboardMutation(spaceId, ({ id, title }: { id: string; title: string }) =>
    apiSend<KeptItem>("PATCH", `/spaces/${spaceId}/dashboards/items/${id}`, { title }),
  );
}

export function useDeleteItem(spaceId: string) {
  return useDashboardMutation(spaceId, (id: string) =>
    apiSend<void>("DELETE", `/spaces/${spaceId}/dashboards/items/${id}`),
  );
}

const KEPT_PAGE = 50;

/** Your kept answers, searched on the server and loaded a page at a time. */
export function useKeptItems(spaceId: string, search: string, enabled = true) {
  const q = search.trim();
  return useInfiniteQuery({
    queryKey: [...dashboardsKey(spaceId), "kept", q],
    enabled,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      apiGet<KeptPage>(
        `/spaces/${spaceId}/dashboards/items?limit=${KEPT_PAGE}&offset=${pageParam}&q=${encodeURIComponent(q)}`,
      ),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });
}

// ── Reports ──────────────────────────────────────────────────────────────────

export function useReportOptions(spaceId: string) {
  return useQuery({
    queryKey: [...reportsKey(spaceId), "options"],
    queryFn: () => apiGet<ReportOptions>(`/spaces/${spaceId}/reports/options`),
  });
}

/** Asks again every few seconds while a report is being made. */
export function useReports(spaceId: string) {
  return useQuery({
    queryKey: reportsKey(spaceId),
    queryFn: () => apiGet<Report[]>(`/spaces/${spaceId}/reports`),
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.last_run?.status === "running") ? 2000 : false,
  });
}

export function useReportRuns(spaceId: string, reportId: string | null) {
  return useQuery({
    queryKey: [...reportsKey(spaceId), reportId, "runs"],
    queryFn: () => apiGet<ReportRun[]>(`/spaces/${spaceId}/reports/${reportId}/runs`),
    enabled: reportId !== null,
    refetchInterval: (query) => (query.state.data?.[0]?.status === "running" ? 2000 : false),
  });
}

function useReportMutation<TVariables, TResult>(
  spaceId: string,
  run: (variables: TVariables) => Promise<TResult>,
  errorToast?: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    meta: errorToast ? { errorToast } : undefined,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: reportsKey(spaceId) }),
  });
}

export function useCreateReport(spaceId: string) {
  return useReportMutation(spaceId, (input: ReportInput) =>
    apiSend<Report>("POST", `/spaces/${spaceId}/reports`, input),
  );
}

export function useUpdateReport(spaceId: string) {
  return useReportMutation(
    spaceId,
    ({ id, changes }: { id: string; changes: Partial<ReportInput> }) =>
      apiSend<Report>("PATCH", `/spaces/${spaceId}/reports/${id}`, changes),
  );
}

export function useDeleteReport(spaceId: string) {
  return useReportMutation(spaceId, (id: string) =>
    apiSend<void>("DELETE", `/spaces/${spaceId}/reports/${id}`),
  );
}

export function useRunReport(spaceId: string) {
  return useReportMutation(
    spaceId,
    (id: string) => apiSend<ReportRun>("POST", `/spaces/${spaceId}/reports/${id}/run`),
    "Could not start the report",
  );
}

/** Saves one file of a report run to the computer. */
export function useDownloadReportFile(spaceId: string) {
  return useMutation({
    meta: { errorToast: "Download failed" },
    mutationFn: async ({
      reportId,
      runId,
      name,
    }: {
      reportId: string;
      runId: string;
      name: string;
    }) => {
      const { blob } = await apiBlob(
        `/spaces/${spaceId}/reports/${reportId}/runs/${runId}/files/${encodeURIComponent(name)}`,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },
  });
}
