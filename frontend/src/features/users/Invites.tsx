import { Check, Copy, MailPlus, RefreshCw, Send, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { SelectField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { asApiError, type Role } from "../../lib/api";
import { plural, timeAgo } from "../../lib/format";
import { useMailStatus } from "../mail/queries";
import { parseEmails } from "./parseEmails";
import {
  useCancelInvite,
  useInvites,
  useResendInvite,
  useSendInvites,
  type InviteResult,
} from "./queries";
import { ROLE_HELP, ROLE_LABEL, ROLE_OPTIONS } from "./roles";

/** Invite people by email: each gets a one-time link to choose their own password. */
export function InvitePanel({ onDone }: { onDone: () => void }) {
  const send = useSendInvites();
  const mail = useMailStatus();
  const [text, setText] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [results, setResults] = useState<InviteResult[] | null>(null);
  const { valid, invalid } = parseEmails(text);
  const error = send.error ? asApiError(send.error) : null;
  const emailReady = mail.data?.configured ?? true;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid.length === 0) return;
    send.mutate(
      { emails: valid, role },
      {
        onSuccess: (done) => {
          setResults(done);
          setText("");
        },
      },
    );
  }

  return (
    <Card className="overflow-hidden rounded-xl">
      <CardHeader
        title="Invite people"
        description="They get an email with a link to choose their own password. No password to share."
      />
      <form onSubmit={submit} noValidate>
        <div className="space-y-4 p-5">
          {!emailReady && (
            <Notice tone="warn" title="Email is not set up yet">
              Invitations will be made, but nothing is emailed. You will get a link for each person
              to send them yourself. Set up email on the Email page to send them automatically.
            </Notice>
          )}
          {error && (
            <Notice tone="error" title="Could not send the invitations">
              {error.message}
            </Notice>
          )}
          {results && <Results results={results} />}
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_14rem]">
            <label className="block space-y-1.5">
              <span className="text-[13px] font-medium">Email addresses</span>
              <textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={3}
                placeholder="asha@company.com, ravi@company.com"
                className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-[14px] placeholder:text-subtle hover:border-border-strong focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
              />
              <span className="block text-[12.5px] text-subtle">
                {valid.length > 0
                  ? `${plural(valid.length, "person")} to invite.`
                  : "Separate several addresses with commas, spaces or new lines."}
                {invalid.length > 0 && (
                  <span className="text-danger">
                    {" "}
                    Not an email address: {invalid.slice(0, 3).join(", ")}
                    {invalid.length > 3 ? "…" : ""}
                  </span>
                )}
              </span>
            </label>
            <div className="space-y-1.5">
              <SelectField
                label="Role"
                options={ROLE_OPTIONS}
                value={role}
                onChange={(event) => setRole(event.target.value as Role)}
              />
              <p className="text-[12.5px] text-subtle">{ROLE_HELP[role]}</p>
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-border bg-surface-2/40 px-5 py-3.5">
          <Button onClick={onDone}>{results ? "Done" : "Cancel"}</Button>
          <Button
            type="submit"
            variant="primary"
            loading={send.isPending}
            disabled={valid.length === 0 || invalid.length > 0}
          >
            <Send aria-hidden />
            Send {valid.length > 1 ? `${valid.length} invitations` : "invitation"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function Results({ results }: { results: InviteResult[] }) {
  const emailed = results.filter((r) => r.outcome === "emailed").length;
  const manual = results.filter((r) => r.outcome === "link");
  const existing = results.filter((r) => r.outcome === "exists");
  return (
    <div className="space-y-3">
      {emailed > 0 && (
        <Notice title={`${plural(emailed, "invitation")} emailed`}>
          Each person has a link that works once and expires in 7 days.
        </Notice>
      )}
      {manual.length > 0 && (
        <Notice tone="warn" title="Send these links yourself">
          <p>
            {manual[0]?.detail ?? "The email could not be sent."} Copy each link and send it to the
            person privately.
          </p>
          <ul className="mt-2 space-y-1.5">
            {manual.map((result) => (
              <li key={result.email} className="flex items-center justify-between gap-3">
                <span className="min-w-0 truncate font-medium">{result.email}</span>
                {result.link && <CopyLink link={result.link} />}
              </li>
            ))}
          </ul>
        </Notice>
      )}
      {existing.length > 0 && (
        <Notice title="Already have an account">
          {existing.map((r) => r.email).join(", ")} can sign in already, so no invitation was made.
        </Notice>
      )}
    </div>
  );
}

function CopyLink({ link, label = "Copy link" }: { link: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(link);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // Clipboard access can be blocked; nothing else to do.
        }
      }}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? "Copied" : label}
    </Button>
  );
}

/** Invitations sent and not used yet. */
export function PendingInvites() {
  const invites = useInvites();
  const resend = useResendInvite();
  const cancel = useCancelInvite();
  const [fresh, setFresh] = useState<InviteResult | null>(null);
  const list = invites.data ?? [];
  if (list.length === 0) return null;
  const error = resend.error ?? cancel.error;

  return (
    <Card className="overflow-hidden rounded-xl">
      <CardHeader
        title={`Waiting to join (${list.length})`}
        description="Invited, but they have not opened the link yet."
      />
      <div className="space-y-3 p-5 pt-0">
        {error && (
          <Notice tone="error" title="That did not work">
            {asApiError(error).message}
          </Notice>
        )}
        {fresh && (
          <Notice
            tone={fresh.outcome === "emailed" ? "info" : "warn"}
            title={
              fresh.outcome === "emailed"
                ? `A new link was emailed to ${fresh.email}`
                : `Send ${fresh.email} this new link yourself`
            }
            action={fresh.outcome === "link" && fresh.link ? <CopyLink link={fresh.link} /> : null}
          >
            The earlier link no longer works.
            {fresh.outcome === "link" && fresh.detail && ` ${fresh.detail}`}
          </Notice>
        )}
      </div>
      <ul className="divide-y divide-border border-t border-border">
        {list.map((invite) => (
          <li key={invite.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
            <MailPlus aria-hidden className="size-4 shrink-0 text-subtle" />
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{invite.email}</p>
              <p className="text-[12.5px] text-subtle">
                {ROLE_LABEL[invite.role]} · invited {timeAgo(invite.created_at)}
                {invite.invited_by && ` by ${invite.invited_by}`} · expires{" "}
                {timeAgo(invite.expires_at)}
              </p>
            </div>
            <Button
              size="sm"
              variant="ghost"
              loading={resend.isPending && resend.variables === invite.id}
              onClick={() => resend.mutate(invite.id, { onSuccess: setFresh })}
            >
              <RefreshCw aria-hidden />
              Send again
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-danger"
              loading={cancel.isPending && cancel.variables === invite.id}
              onClick={() => cancel.mutate(invite.id)}
            >
              <Trash2 aria-hidden />
              Cancel
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
