import { Check, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { Button } from "../../components/ui/Button";
import { TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { useFeedback } from "./queries";

/**
 * Thumbs up or down on an answer, with an optional comment after a thumbs down. Feedback tells
 * the people who maintain the space where answers go wrong; it never changes answers by itself.
 */
export function FeedbackRow({
  spaceId,
  conversationId,
  messageId,
  rating,
  comment,
}: {
  spaceId: string;
  conversationId: string;
  messageId: string;
  rating: "up" | "down" | null;
  comment: string | null;
}) {
  const feedback = useFeedback(spaceId, conversationId);
  const [asking, setAsking] = useState(false);
  const [text, setText] = useState(comment ?? "");
  const [sent, setSent] = useState(false);
  const error = feedback.error ? asApiError(feedback.error).message : null;

  function choose(next: "up" | "down") {
    setSent(false);
    if (rating === next) {
      setAsking(false);
      feedback.mutate({ messageId, rating: null });
      return;
    }
    feedback.mutate({ messageId, rating: next, comment: "" });
    setAsking(next === "down");
  }

  function sendComment() {
    feedback.mutate(
      { messageId, rating: "down", comment: text.trim() },
      {
        onSuccess: () => {
          setAsking(false);
          setSent(true);
        },
      },
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1" role="group" aria-label="Was this answer helpful?">
        {(
          [
            ["up", "Good answer", ThumbsUp],
            ["down", "Bad answer", ThumbsDown],
          ] as const
        ).map(([value, label, Icon]) => (
          <Button
            key={value}
            variant="ghost"
            size="icon"
            aria-label={label}
            aria-pressed={rating === value}
            disabled={feedback.isPending}
            className={cn(rating === value && "bg-surface-2 text-accent")}
            onClick={() => choose(value)}
          >
            <Icon aria-hidden />
          </Button>
        ))}
        {sent && (
          <span role="status" className="ml-1 flex items-center gap-1 text-[12.5px] text-muted">
            <Check aria-hidden className="size-3.5 text-success" />
            Thanks, this was passed on.
          </span>
        )}
      </div>
      {error && (
        <Notice tone="error" title="Feedback not saved">
          {error}
        </Notice>
      )}
      {asking && (
        <div className="space-y-2 rounded-md border border-border bg-surface-2/40 p-3">
          <TextField
            label="What was wrong? (optional)"
            placeholder="e.g. the totals look too low"
            maxLength={1000}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>
              Skip
            </Button>
            <Button size="sm" variant="primary" loading={feedback.isPending} onClick={sendComment}>
              Send
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
