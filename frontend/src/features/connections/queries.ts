import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "../../lib/api";
import type { AuditEvent, Connection, ConnectionTest } from "./types";

const CONNECTIONS = ["connections"] as const;
const AUDIT = [...CONNECTIONS, "audit"] as const;

export function useConnections() {
  return useQuery({
    queryKey: CONNECTIONS,
    queryFn: () => apiGet<Connection[]>("/connections"),
  });
}

export function useAuditTrail(enabled: boolean) {
  return useQuery({
    queryKey: AUDIT,
    queryFn: () => apiGet<AuditEvent[]>("/connections/audit?limit=30"),
    enabled,
  });
}

function useChanged() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: CONNECTIONS });
}

export function useCreateConnection() {
  const changed = useChanged();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend<Connection>("POST", "/connections", body),
    onSuccess: changed,
  });
}

export function useUpdateConnection() {
  const changed = useChanged();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      apiSend<Connection>("PATCH", `/connections/${id}`, body),
    onSuccess: changed,
  });
}

export function useDeleteConnection() {
  const changed = useChanged();
  return useMutation({
    mutationFn: (id: string) => apiSend<void>("DELETE", `/connections/${id}`),
    onSuccess: changed,
  });
}

export function useTestConnection() {
  const changed = useChanged();
  return useMutation({
    mutationFn: (id: string) => apiSend<ConnectionTest>("POST", `/connections/${id}/test`),
    onSuccess: changed,
  });
}

/** Connect with an admin login once, to have a read-only login made. Only that login is saved. */
export function useProvisionConnection() {
  const changed = useChanged();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      apiSend<ConnectionTest>("POST", "/connections/provision", body),
    onSuccess: changed,
  });
}

/** For a blocked connection: make a read-only login with its own login, once, and switch to it. */
export function useMakeReadOnly() {
  const changed = useChanged();
  return useMutation({
    mutationFn: (id: string) =>
      apiSend<ConnectionTest>("POST", `/connections/${id}/make-read-only`, {}),
    onSuccess: changed,
  });
}
