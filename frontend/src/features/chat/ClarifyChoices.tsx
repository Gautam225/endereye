import { Check, SendHorizontal } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import { composeReply, toggleChoice } from "./clarify";

/**
 * The answers the assistant offers with a question it asks, and a box to write one's own. Pick
 * one or more, add words if you like, and send: what is sent is an ordinary message, so the
 * assistant reads it together with the question it asked.
 */
export function ClarifyChoices({
  options,
  onAnswer,
}: {
  options: string[];
  onAnswer: (reply: string) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [typed, setTyped] = useState("");
  const [sent, setSent] = useState(false);
  const reply = composeReply(selected, typed);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!reply || sent) return;
    setSent(true);
    onAnswer(reply);
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Answer the question"
      className="space-y-2.5 rounded-xl border border-border bg-surface-2/30 p-3"
    >
      <fieldset disabled={sent} className="space-y-2.5">
        <legend className="mb-2 text-[12.5px] text-subtle">
          Pick one or more answers, or write your own
        </legend>
        <div className="flex flex-wrap gap-2">
          {options.map((option) => {
            const on = selected.includes(option);
            return (
              <button
                key={option}
                type="button"
                aria-pressed={on}
                onClick={() => setSelected((current) => toggleChoice(current, option, options))}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-left text-[13px] transition-colors",
                  on
                    ? "border-accent bg-accent-soft text-fg"
                    : "border-border bg-surface hover:border-border-strong hover:bg-surface-2",
                )}
              >
                {on && <Check aria-hidden className="size-3.5 text-accent" />}
                {option}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="Or write your own answer, or add to the ones above…"
            aria-label="Your own answer"
            maxLength={500}
            className="block h-9 min-w-0 flex-1 rounded-md border border-border bg-bg px-3 text-[14px] text-fg transition-[border-color,box-shadow] duration-150 placeholder:text-subtle hover:border-border-strong focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
          />
          <Button type="submit" variant="primary" disabled={!reply} loading={sent}>
            <SendHorizontal aria-hidden />
            Send
          </Button>
        </div>
      </fieldset>
    </form>
  );
}
