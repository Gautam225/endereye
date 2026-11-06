import { ArrowLeft, GitBranch, Lock } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router";

import { Button } from "../../components/ui/Button";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { asApiError } from "../../lib/api";
import { timeAgo } from "../../lib/format";
import { AnswerCard } from "./AnswerCard";
import { viewOfMessage } from "./answerView";
import { Turn } from "./ChatPage";
import { useBranchShared, useSharedChat } from "./queries";

/**
 * A chat someone shared with you, to read. The answers keep their citations, and the pages they
 * point at open for you. To carry on, branch it into a chat of your own.
 */
export function SharedChatPage() {
  const { conversationId = "" } = useParams();
  const chat = useSharedChat(conversationId);
  const branch = useBranchShared();
  const navigate = useNavigate();

  function carryOn() {
    branch.mutate(conversationId, {
      onSuccess: (made) => void navigate(`/spaces/${made.space_id}/chat/${made.id}`),
    });
  }

  if (chat.isPending) {
    return (
      <div className="mx-auto max-w-4xl space-y-6 px-5 py-8">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="ml-auto h-10 w-2/3" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (chat.isError) {
    return (
      <div className="mx-auto max-w-2xl px-5 py-12">
        <EmptyState icon={Lock} title="You can't open this chat">
          {asApiError(chat.error).message}{" "}
          <Link to="/chat" className="text-accent underline-offset-2 hover:underline">
            Back to chat
          </Link>
        </EmptyState>
      </div>
    );
  }

  const { data } = chat;
  return (
    <div className="mx-auto w-full max-w-4xl px-5 py-8 md:px-8">
      <Link
        to="/chat"
        className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-muted transition-colors hover:text-fg"
      >
        <ArrowLeft aria-hidden className="size-3.5" />
        Back to chat
      </Link>
      <header className="mb-8 flex flex-wrap items-start justify-between gap-4 border-b border-border pb-5">
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold tracking-[-0.01em]">{data.title}</h1>
          <p className="mt-1 text-[13.5px] text-muted">
            Shared by {data.owner_name ?? "someone"} · {data.space_name} · updated{" "}
            {timeAgo(data.updated_at)}
          </p>
        </div>
        <Button variant="primary" loading={branch.isPending} onClick={carryOn}>
          <GitBranch aria-hidden />
          Continue in my own chat
        </Button>
      </header>

      {branch.error && (
        <Notice tone="error" title="Could not make your copy" className="mb-6">
          {asApiError(branch.error).message}
        </Notice>
      )}

      <div className="space-y-10" role="log" aria-label="Shared conversation">
        {data.messages.map((message) => (
          <Turn
            key={message.id}
            question={message.question}
            mentions={message.mentions.map((m) => m.name)}
            canEdit={false}
            editing={false}
          >
            <AnswerCard
              view={viewOfMessage(message)}
              spaceId={data.space_id}
              conversationId={data.id}
              editor={false}
              readOnly
              isLast={false}
              onAsk={() => undefined}
              onStop={() => undefined}
            />
          </Turn>
        ))}
      </div>

      <p className="mt-10 flex items-center gap-2 rounded-xl border border-border bg-surface px-4 py-3 text-[13.5px] text-muted">
        <Lock aria-hidden className="size-4 shrink-0 text-subtle" />
        You can read this chat and open the pages it cites. It stays unchanged: continue in your own
        copy to ask more.
      </p>
    </div>
  );
}
