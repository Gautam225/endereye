import { Check, Plus } from "lucide-react";
import { Link } from "react-router";

import { BareTextArea } from "../../components/ui/Field";
import { cn } from "../../lib/cn";
import { useAuth } from "../../lib/auth";
import { useRecipients } from "../mail/queries";
import { parseRecipients, toggleRecipient } from "./schedule";

/**
 * Who a report or an alert goes to: addresses can be typed, or picked from your saved list with
 * one click (your own address is always offered). The list is kept on the Account page.
 */
export function RecipientsField({
  id,
  label,
  value,
  onChange,
  help,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (text: string) => void;
  help?: string;
}) {
  const { user } = useAuth();
  const saved = useRecipients();
  const typed = new Set(parseRecipients(value));
  const options = [
    ...(user ? [{ email: user.email.toLowerCase(), name: "Me" }] : []),
    ...(saved.data ?? [])
      .filter((r) => r.email !== user?.email.toLowerCase())
      .map((r) => ({ email: r.email, name: r.label || r.email })),
  ];

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium">
        {label}
      </label>
      {options.length > 0 && (
        <ul aria-label="Saved addresses" className="flex flex-wrap gap-1.5">
          {options.map((option) => {
            const on = typed.has(option.email);
            return (
              <li key={option.email}>
                <button
                  type="button"
                  aria-pressed={on}
                  title={option.email}
                  onClick={() => onChange(toggleRecipient(value, option.email))}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[12.5px] transition-colors",
                    on
                      ? "border-accent/50 bg-accent-soft text-fg"
                      : "border-border text-muted hover:bg-surface-2/60 hover:text-fg",
                  )}
                >
                  {on ? (
                    <Check aria-hidden className="size-3" />
                  ) : (
                    <Plus aria-hidden className="size-3" />
                  )}
                  {option.name}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <BareTextArea
        id={id}
        rows={2}
        value={value}
        placeholder="name@company.com, other@company.com"
        onChange={(event) => onChange(event.target.value)}
      />
      <p className="text-[12.5px] text-subtle">
        {help}{" "}
        <Link to="/email" className="text-accent underline-offset-2 hover:underline">
          Manage your saved people
        </Link>
      </p>
    </div>
  );
}
