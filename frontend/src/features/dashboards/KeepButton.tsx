import { Check, Pin } from "lucide-react";
import { Link } from "react-router";

import { Button } from "../../components/ui/Button";
import { asApiError } from "../../lib/api";
import { usePinAnswer } from "./queries";

/** Keeps an answer on a dashboard, so it can be refreshed later instead of asked again. */
export function KeepButton({
  spaceId,
  conversationId,
  messageId,
}: {
  spaceId: string;
  conversationId: string;
  messageId: string;
}) {
  const pin = usePinAnswer(spaceId);

  if (pin.isSuccess) {
    return (
      <Link
        to={`/spaces/${spaceId}/dashboards`}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[13px] text-muted hover:text-fg"
      >
        <Check aria-hidden className="size-3.5 text-accent" />
        Kept · View dashboard
      </Link>
    );
  }
  return (
    <>
      <Button
        size="sm"
        loading={pin.isPending}
        onClick={() => pin.mutate({ conversationId, messageId })}
        title="Keep this answer on a dashboard and refresh it later instead of asking again"
      >
        <Pin aria-hidden className="size-3.5" />
        Keep
      </Button>
      {pin.error && (
        <span role="alert" className="text-[12.5px] text-danger">
          {asApiError(pin.error).message}
        </span>
      )}
    </>
  );
}
