import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Navigate } from "react-router";

import { Notice } from "../../components/ui/Notice";
import { apiGet } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { forgetChat, lastChat } from "./lastSpace";
import { useGeneralSpace } from "./queries";

/**
 * Where "Ask" in the menu leads: back to the chat you were last in, in the space you were
 * working in, so leaving for another page and coming back never loses your place. If that chat
 * or space is gone (deleted, or you were removed), or there is none yet, it is the general chat:
 * an ordinary conversation that needs no space. A space is chosen from the switcher at the top
 * of the chat when you want its data.
 */
export function ChatHome() {
  const { user } = useAuth();
  // Read once, when the page opens: the chat itself keeps this up to date while you use it.
  const [last] = useState(() => (user ? lastChat(user.id) : null));

  // Is the remembered chat (or, for a chat not yet started, its space) still there?
  const check = useQuery({
    queryKey: ["chat", "last-check", last?.spaceId, last?.conversationId],
    enabled: last !== null,
    retry: false,
    staleTime: 60_000, // the chat was checked a moment ago: opening it again needs no new request
    gcTime: 60_000,
    queryFn: async () => {
      if (!last) return false;
      await apiGet(
        last.conversationId
          ? `/spaces/${last.spaceId}/conversations/${last.conversationId}`
          : `/spaces/${last.spaceId}`,
      );
      return true;
    },
  });
  const gone = last !== null && check.isError;
  const general = useGeneralSpace();

  useEffect(() => {
    if (gone && user) forgetChat(user.id);
  }, [gone, user]);

  if (last && check.isSuccess) {
    const path = last.conversationId
      ? `/spaces/${last.spaceId}/chat/${last.conversationId}`
      : `/spaces/${last.spaceId}/chat`;
    return <Navigate to={path} replace />;
  }

  if ((last && check.isPending) || general.isPending) {
    // Nothing to show: this page only passes you on to a chat. A skeleton here would flash for
    // a moment and then be replaced by the chat's own.
    return null;
  }
  if (general.isError) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <Notice tone="error" title="Could not open the chat">
          {general.error.message}
        </Notice>
      </div>
    );
  }
  return <Navigate to={`/spaces/${general.data.id}/chat`} replace />;
}
