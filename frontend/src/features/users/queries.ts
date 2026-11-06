import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend, type Role, type User } from "../../lib/api";

const USERS = ["users"] as const;

export function useUsers() {
  return useQuery({ queryKey: USERS, queryFn: () => apiGet<User[]>("/users") });
}

export interface NewUser {
  full_name: string;
  email: string;
  role: Role;
  password: string;
}

export type UserChange = Partial<{
  full_name: string;
  role: Role;
  is_active: boolean;
  password: string;
}>;

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: NewUser) => apiSend<User>("POST", "/users", input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS }),
  });
}

export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, change }: { id: string; change: UserChange }) =>
      apiSend<User>("PATCH", `/users/${id}`, change),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS }),
  });
}

// ── Invitations ──────────────────────────────────────────────────────────────

const INVITES = ["users", "invites"] as const;

export interface Invite {
  id: string;
  email: string;
  role: Role;
  created_at: string;
  expires_at: string;
  invited_by: string | null;
}

/** What happened to one address. `link` lets an admin pass the invitation on by hand. */
export interface InviteResult {
  email: string;
  outcome: "emailed" | "link" | "exists";
  link: string | null;
  detail: string | null;
  invite: Invite | null;
}

export function useInvites() {
  return useQuery({ queryKey: INVITES, queryFn: () => apiGet<Invite[]>("/users/invites") });
}

export function useSendInvites() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { emails: string[]; role: Role }) =>
      apiSend<InviteResult[]>("POST", "/users/invites", input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: INVITES }),
  });
}

export function useResendInvite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiSend<InviteResult>("POST", `/users/invites/${id}/resend`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: INVITES }),
  });
}

export function useCancelInvite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiSend<void>("DELETE", `/users/invites/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: INVITES }),
  });
}
