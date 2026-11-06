import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "../../lib/api";

export interface MailSettings {
  configured: boolean;
  /** Set up in the app, taken from the server's .env, or not set up. */
  source: "app" | "env" | "none";
  host: string;
  port: number;
  security: "starttls" | "ssl" | "none";
  username: string;
  from_address: string;
  has_password: boolean;
  /** A password can be stored (the server has an encryption key). */
  vault_ready: boolean;
  allowed_domains: string[];
  updated_at: string | null;
  updated_by_name: string | null;
}

export interface MailInput {
  host: string;
  port: number;
  security: MailSettings["security"];
  username: string;
  /** Leave out to keep the saved password; "" removes it. */
  password?: string;
  from_address: string;
}

export interface MailTestResult {
  ok: boolean;
  message: string;
  sent_to: string;
}

export interface SavedRecipient {
  id: string;
  email: string;
  label: string;
  created_at: string;
}

export interface MailStatus {
  configured: boolean;
  from_address: string;
}

const MAIL = ["mail"] as const;
const RECIPIENTS = ["me", "recipients"] as const;

export function useMailSettings() {
  return useQuery({ queryKey: MAIL, queryFn: () => apiGet<MailSettings>("/mail") });
}

/** Whether mail is set up changes what the Reports and Alerts pages say, so they are refreshed too. */
function useMailMutation<TVariables, TResult>(run: (variables: TVariables) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: MAIL }),
        queryClient.invalidateQueries({ queryKey: ["spaces"] }),
      ]),
  });
}

/** Whether email works, for anyone signed in. The settings behind it are for administrators. */
export function useMailStatus() {
  return useQuery({
    queryKey: [...MAIL, "status"],
    queryFn: () => apiGet<MailStatus>("/mail/status"),
  });
}

export function useSaveMail() {
  return useMailMutation((input: MailInput) => apiSend<MailSettings>("PUT", "/mail", input));
}

export function useClearMail() {
  return useMailMutation(() => apiSend<MailSettings>("DELETE", "/mail"));
}

export function useSendTestMail() {
  return useMutation({
    mutationFn: (to: string) =>
      apiSend<MailTestResult>("POST", "/mail/test", { to: to.trim() || null }),
  });
}

// ── Saved addresses (every person has their own list) ────────────────────────

export function useRecipients() {
  return useQuery({
    queryKey: RECIPIENTS,
    queryFn: () => apiGet<SavedRecipient[]>("/me/recipients"),
  });
}

function useRecipientMutation<TVariables, TResult>(
  run: (variables: TVariables) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RECIPIENTS }),
  });
}

export function useAddRecipient() {
  return useRecipientMutation((input: { email: string; label: string }) =>
    apiSend<SavedRecipient>("POST", "/me/recipients", input),
  );
}

export function useDeleteRecipient() {
  return useRecipientMutation((id: string) => apiSend<void>("DELETE", `/me/recipients/${id}`));
}
