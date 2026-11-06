import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "../../lib/api";
import type { Correction, Detail, Filters, ReviewStatus, RowList, Summary } from "./types";

export const PAGE_SIZE = 25;
const KEY = ["monitoring"] as const;

function scope(filters: Filters): URLSearchParams {
  const params = new URLSearchParams({ days: String(filters.days) });
  if (filters.spaceId) params.set("space_id", filters.spaceId);
  return params;
}

export function useSummary(filters: Filters) {
  return useQuery({
    queryKey: [...KEY, "summary", filters.days, filters.spaceId],
    queryFn: () => apiGet<Summary>(`/admin/monitoring/summary?${scope(filters)}`),
    placeholderData: keepPreviousData,
  });
}

export function useMessages(filters: Filters) {
  const params = scope(filters);
  if (filters.status) params.set("status", filters.status);
  if (filters.feedback) params.set("feedback", filters.feedback);
  if (filters.review) params.set("review", filters.review);
  if (filters.text) params.set("q", filters.text);
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String(filters.offset));
  return useQuery({
    queryKey: [...KEY, "messages", params.toString()],
    queryFn: () => apiGet<RowList>(`/admin/monitoring/messages?${params}`),
    placeholderData: keepPreviousData,
  });
}

export function useDetail(id: string | null) {
  return useQuery({
    queryKey: [...KEY, "detail", id],
    queryFn: () => apiGet<Detail>(`/admin/monitoring/messages/${id}`),
    enabled: id !== null,
  });
}

function useChanged() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: KEY });
}

export function useReview(id: string) {
  const changed = useChanged();
  return useMutation({
    mutationFn: (input: { status: ReviewStatus; note: string }) =>
      apiSend<Detail>("POST", `/admin/monitoring/messages/${id}/review`, input),
    onSuccess: changed,
  });
}

export function useCorrect(id: string) {
  const changed = useChanged();
  return useMutation({
    mutationFn: (input: Correction) =>
      apiSend<{ example_id: string; row_count: number; detail: Detail }>(
        "POST",
        `/admin/monitoring/messages/${id}/correct`,
        input,
      ),
    onSuccess: changed,
  });
}
