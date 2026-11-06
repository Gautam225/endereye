import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiBlob, apiGet, apiSend, apiUpload } from "../../lib/api";
import { documentsPollInterval } from "../spaces/documents";
import type { DocumentInfo, Space } from "../spaces/types";
import type {
  ChatMessage,
  Conversation,
  ConversationDetail,
  DiscoverHit,
  InboxItem,
  SharedChat,
  SharedConversation,
  Shares,
} from "./types";

/** Someone who can be picked to share a chat with. */
export interface Person {
  id: string;
  full_name: string;
  email: string;
}

const chat = (spaceId: string) => ["spaces", spaceId, "chat"] as const;
const list = (spaceId: string) => [...chat(spaceId), "conversations"] as const;
const detail = (spaceId: string, id: string) => [...chat(spaceId), "conversation", id] as const;

export function useConversations(spaceId: string, search: string) {
  return useQuery({
    queryKey: [...list(spaceId), search],
    queryFn: () =>
      apiGet<Conversation[]>(
        `/spaces/${spaceId}/conversations?limit=100${search ? `&q=${encodeURIComponent(search)}` : ""}`,
      ),
  });
}

export function useConversation(spaceId: string, id: string | undefined) {
  return useQuery({
    queryKey: detail(spaceId, id ?? ""),
    queryFn: () => apiGet<ConversationDetail>(`/spaces/${spaceId}/conversations/${id}`),
    enabled: Boolean(id),
  });
}

export function useSuggestions(spaceId: string) {
  return useQuery({
    queryKey: [...chat(spaceId), "suggestions"],
    queryFn: () => apiGet<string[]>(`/spaces/${spaceId}/suggestions`),
    staleTime: 60_000,
  });
}

export function useDiscover(spaceId: string, text: string) {
  return useQuery({
    queryKey: [...chat(spaceId), "discover", text],
    queryFn: () =>
      apiGet<DiscoverHit[]>(`/spaces/${spaceId}/discover?q=${encodeURIComponent(text)}`),
    enabled: text.length > 0,
  });
}

/** Called when a turn finishes or a thread changes, so lists and the thread are fresh. */
export function useRefreshChat(spaceId: string) {
  const queryClient = useQueryClient();
  return async (conversationId?: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: list(spaceId) }),
      conversationId
        ? queryClient.invalidateQueries({ queryKey: detail(spaceId, conversationId) })
        : undefined,
    ]);
  };
}

export function useCreateConversation(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<Conversation>("POST", `/spaces/${spaceId}/conversations`, {}),
    onSuccess: (created) => {
      // Known to be empty, so opening it does not show a loading state first.
      queryClient.setQueryData<ConversationDetail>(detail(spaceId, created.id), {
        ...created,
        messages: [],
      });
      return queryClient.invalidateQueries({ queryKey: list(spaceId) });
    },
  });
}

export function useRenameConversation(spaceId: string) {
  const refresh = useRefreshChat(spaceId);
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiSend<Conversation>("PATCH", `/spaces/${spaceId}/conversations/${id}`, { title }),
    onSuccess: (_, { id }) => refresh(id),
  });
}

export function useSharedConversations(spaceId: string) {
  return useQuery({
    queryKey: [...chat(spaceId), "shared"],
    queryFn: () => apiGet<SharedConversation[]>(`/spaces/${spaceId}/conversations/shared`),
  });
}

/** Let the other members of the space read a chat of yours, or stop. */
export function useShareConversation(spaceId: string) {
  const refresh = useRefreshChat(spaceId);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, shared }: { id: string; shared: boolean }) =>
      apiSend<Conversation>("PATCH", `/spaces/${spaceId}/conversations/${id}`, { shared }),
    onSuccess: async (_, { id }) => {
      await refresh(id);
      await queryClient.invalidateQueries({ queryKey: [...chat(spaceId), "shared"] });
    },
  });
}

/** Branch a chat (up to and including an answer) into a new chat of your own. */
export function useForkConversation(spaceId: string) {
  const refresh = useRefreshChat(spaceId);
  return useMutation({
    mutationFn: ({ id, messageId }: { id: string; messageId?: string }) =>
      apiSend<Conversation>("POST", `/spaces/${spaceId}/conversations/${id}/fork`, {
        message_id: messageId ?? null,
      }),
    onSuccess: () => refresh(),
  });
}

/** Pin a chat to the top of the list, or let it go back to its place by date. */
export function usePinConversation(spaceId: string) {
  const refresh = useRefreshChat(spaceId);
  return useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      apiSend<Conversation>("PATCH", `/spaces/${spaceId}/conversations/${id}`, { pinned }),
    onSuccess: (_, { id }) => refresh(id),
  });
}

export function useDeleteConversation(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiSend<void>("DELETE", `/spaces/${spaceId}/conversations/${id}`),
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: detail(spaceId, id) });
      return queryClient.invalidateQueries({ queryKey: list(spaceId) });
    },
  });
}

export function useFeedback(spaceId: string, conversationId: string) {
  const refresh = useRefreshChat(spaceId);
  return useMutation({
    mutationFn: ({
      messageId,
      rating,
      comment,
    }: {
      messageId: string;
      rating: "up" | "down" | null;
      comment?: string;
    }) => {
      const path = `/spaces/${spaceId}/conversations/${conversationId}/messages/${messageId}/feedback`;
      return rating
        ? apiSend<ChatMessage>("PUT", path, { rating, comment: comment ?? "" })
        : apiSend<ChatMessage>("DELETE", path);
    },
    onSuccess: () => refresh(conversationId),
  });
}

/** Fetches the full result as CSV and hands it to the browser as a file. */
/** The full result as a file: CSV, or an Excel workbook with the answer and the SQL beside it. */
export function useDownloadResult(spaceId: string, conversationId: string, kind: "csv" | "xlsx") {
  return useMutation({
    mutationFn: async (messageId: string) => {
      const { blob, filename } = await apiBlob(
        `/spaces/${spaceId}/conversations/${conversationId}/messages/${messageId}/${kind}`,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },
  });
}

// ── The general chat, and documents added inside a chat ──────────────────────

/** The space behind the general chat: made the first time it is asked for. */
export function useGeneralSpace() {
  return useQuery({
    queryKey: ["chat", "general-space"],
    queryFn: () => apiSend<Space>("POST", "/chat/general"),
    staleTime: Infinity,
  });
}

const chatDocuments = (spaceId: string, conversationId: string) =>
  [...chat(spaceId), "documents", conversationId] as const;

export function useChatDocuments(spaceId: string, conversationId: string | undefined) {
  return useQuery({
    queryKey: chatDocuments(spaceId, conversationId ?? ""),
    queryFn: () =>
      apiGet<DocumentInfo[]>(`/spaces/${spaceId}/conversations/${conversationId}/documents`),
    enabled: Boolean(conversationId),
    refetchInterval: (query) => documentsPollInterval(query.state.data),
  });
}

export function useUploadChatDocument(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ conversationId, file }: { conversationId: string; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return apiUpload<DocumentInfo>(
        `/spaces/${spaceId}/conversations/${conversationId}/documents`,
        form,
      );
    },
    meta: { errorToast: "Upload failed" },
    onSuccess: (_, { conversationId }) =>
      queryClient.invalidateQueries({ queryKey: chatDocuments(spaceId, conversationId) }),
  });
}

export function useDeleteChatDocument(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ conversationId, id }: { conversationId: string; id: string }) =>
      apiSend<void>("DELETE", `/spaces/${spaceId}/conversations/${conversationId}/documents/${id}`),
    onSuccess: (_, { conversationId }) =>
      queryClient.invalidateQueries({ queryKey: chatDocuments(spaceId, conversationId) }),
  });
}

// ── Sharing ──────────────────────────────────────────────────────────────────

const sharedKey = ["shared-chats"] as const;

/** Who one of your chats is shared with. */
export function useShares(spaceId: string, conversationId: string, enabled = true) {
  return useQuery({
    queryKey: [...detail(spaceId, conversationId), "shares"],
    enabled,
    queryFn: () => apiGet<Shares>(`/spaces/${spaceId}/conversations/${conversationId}/shares`),
  });
}

/** Choose exactly who can read a chat of yours. */
export function useSetShares(spaceId: string, conversationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userIds: string[]) =>
      apiSend<Shares>("PUT", `/spaces/${spaceId}/conversations/${conversationId}/shares`, {
        user_ids: userIds,
      }),
    onSuccess: (shares) => {
      queryClient.setQueryData([...detail(spaceId, conversationId), "shares"], shares);
    },
  });
}

/** People to share with, found by name or email. */
export function usePeople(query: string) {
  return useQuery({
    queryKey: ["people", query],
    queryFn: () => apiGet<Person[]>(`/people?q=${encodeURIComponent(query)}`),
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });
}

/** Chats shared with you. Checked now and then, so a new one shows up without a reload. */
export function useSharedInbox() {
  return useQuery({
    queryKey: sharedKey,
    queryFn: () => apiGet<InboxItem[]>("/shared-chats"),
    refetchInterval: 60_000,
  });
}

export function useSharedChat(id: string) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: [...sharedKey, id],
    queryFn: async () => {
      const found = await apiGet<SharedChat>(`/shared-chats/${id}`);
      // Opening it is what marks it as seen.
      void queryClient.invalidateQueries({ queryKey: sharedKey, exact: true });
      return found;
    },
    retry: false,
  });
}

/** Copy a shared chat into a chat of your own, to carry on from. */
export function useBranchShared() {
  return useMutation({
    mutationFn: (id: string) =>
      apiSend<Conversation & { space_id?: string }>("POST", `/shared-chats/${id}/branch`),
  });
}
