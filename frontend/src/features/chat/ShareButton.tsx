import { Share2, Users } from "lucide-react";
import { useState } from "react";

import { Button } from "../../components/ui/Button";
import { ShareDialog } from "./ShareDialog";
import { useShares } from "./queries";

/**
 * Share a chat with chosen people (or, in a space, everyone in it): they can read it and open the
 * documents it cites, and branch a copy of their own, but not change yours.
 */
export function ShareButton({
  spaceId,
  conversationId,
  title,
  shared,
  personal,
}: {
  spaceId: string;
  conversationId: string;
  title: string;
  /** Open to everyone in the space. */
  shared: boolean;
  /** A General chat has no space to share with, only chosen people. */
  personal: boolean;
}) {
  const [open, setOpen] = useState(false);
  // Fetched once the page knows the chat, so the button can say how many people have it.
  const shares = useShares(spaceId, conversationId);
  const people = shares.data?.people.length ?? 0;
  const active = people > 0 || shared;

  return (
    <>
      <Button
        size="sm"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        title="Choose who can read this chat"
      >
        {active ? (
          <Users aria-hidden className="size-3.5" />
        ) : (
          <Share2 aria-hidden className="size-3.5" />
        )}
        {shared ? "Shared with the space" : people > 0 ? `Shared with ${people}` : "Share"}
      </Button>
      {open && (
        <ShareDialog
          spaceId={spaceId}
          conversationId={conversationId}
          title={title}
          everyone={shared}
          personal={personal}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
