import { Mail, Plus, Search, Trash2, UsersRound } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { BareTextArea, TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { asApiError } from "../../lib/api";
import { initials } from "../../lib/format";
import { isEmail, parseAddresses } from "./addresses";
import { useAddRecipient, useDeleteRecipient, useRecipients, type SavedRecipient } from "./queries";

const LIMIT = 100;
const SEARCH_FROM = 6; // a search box appears once the list is long enough to need one

/**
 * The people you send reports and alerts to. Save an address once here, then pick it with a click
 * when you set a report or an alert up. Each person has their own list; nobody else sees it.
 */
export function PeopleSection() {
  const recipients = useRecipients();
  const [find, setFind] = useState("");
  const all = recipients.data ?? [];
  const word = find.trim().toLowerCase();
  const shown = word
    ? all.filter((r) => r.email.includes(word) || r.label.toLowerCase().includes(word))
    : all;

  return (
    <Card>
      <CardHeader
        title={
          <>
            <UsersRound aria-hidden className="size-4 text-accent" />
            People you send to
          </>
        }
        description="Save an address once, then pick it with one click when you make a report or an alert. Only you can see this list."
        aside={
          all.length > 0 && (
            <span className="text-[12.5px] text-subtle">
              {all.length} of {LIMIT} saved
            </span>
          )
        }
      />
      <AddPeople saved={all.map((r) => r.email)} room={LIMIT - all.length} />

      <div className="border-t border-border">
        {recipients.isPending ? (
          <div className="space-y-2 p-5">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        ) : recipients.isError ? (
          <p className="p-5 text-[13px] text-muted">{recipients.error.message}</p>
        ) : all.length === 0 ? (
          <div className="flex flex-col items-center px-6 py-10 text-center">
            <span className="mb-3 flex size-11 items-center justify-center rounded-full border border-border bg-surface-2 text-muted">
              <Mail aria-hidden className="size-5" />
            </span>
            <p className="font-medium">Nobody saved yet</p>
            <p className="mt-1 max-w-sm text-[13px] text-muted">
              Add your manager, a team inbox or yourself above. They will show up as one-click
              choices when you set up a report or an alert.
            </p>
          </div>
        ) : (
          <>
            {all.length >= SEARCH_FROM && (
              <label className="flex items-center gap-2 border-b border-border px-5 py-2.5 focus-within:bg-surface-2/40">
                <Search aria-hidden className="size-4 shrink-0 text-subtle" />
                <input
                  value={find}
                  onChange={(event) => setFind(event.target.value)}
                  aria-label="Search your saved people"
                  placeholder="Search by name or address"
                  className="h-8 w-full bg-transparent text-[14px] outline-none placeholder:text-subtle"
                />
              </label>
            )}
            {shown.length === 0 ? (
              <p className="px-5 py-8 text-center text-[13px] text-muted">
                No one matches “{find.trim()}”.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {shown.map((item) => (
                  <Row key={item.id} item={item} />
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

// ── Adding ───────────────────────────────────────────────────────────────────

function AddPeople({ saved, room }: { saved: string[]; room: number }) {
  const add = useAddRecipient();
  const [several, setSeveral] = useState(false);
  const [email, setEmail] = useState("");
  const [label, setLabel] = useState("");
  const [pasted, setPasted] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const parsed = parseAddresses(pasted);
  const fresh = parsed.valid.filter((address) => !saved.includes(address));
  const already = parsed.valid.length - fresh.length;
  const problem =
    touched && email.trim() !== "" && !isEmail(email)
      ? "That doesn't look like an email address. It needs an @ and a domain, like name@company.com."
      : undefined;

  function addOne(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    setReport(null);
    if (!isEmail(email)) return;
    add.mutate(
      { email: email.trim(), label: label.trim() },
      {
        onSuccess: () => {
          setReport(`${email.trim().toLowerCase()} was saved.`);
          setEmail("");
          setLabel("");
          setTouched(false);
        },
      },
    );
  }

  async function addMany(event: FormEvent) {
    event.preventDefault();
    const toAdd = fresh.slice(0, Math.max(room, 0));
    if (toAdd.length === 0) return;
    setBusy(true);
    setReport(null);
    setFailure(null);
    let done = 0;
    let lastProblem: string | null = null;
    for (const address of toAdd) {
      try {
        await add.mutateAsync({ email: address, label: "" });
        done += 1;
      } catch (caught) {
        lastProblem = asApiError(caught).message;
      }
    }
    setBusy(false);
    if (done > 0) {
      setReport(`${done} ${done === 1 ? "person" : "people"} saved.`);
      setPasted("");
    }
    if (lastProblem && done < toAdd.length) setFailure(lastProblem);
  }

  return (
    <div className="space-y-3 px-5 pb-5">
      {!several ? (
        <form
          onSubmit={addOne}
          noValidate
          className="grid gap-3 sm:grid-cols-[1.3fr_1fr_auto] sm:items-start"
        >
          <TextField
            label="Email address"
            type="email"
            autoComplete="off"
            value={email}
            error={problem}
            placeholder="name@company.com"
            onChange={(event) => setEmail(event.target.value)}
            onBlur={() => setTouched(true)}
          />
          <TextField
            label="Name (optional)"
            value={label}
            maxLength={120}
            autoComplete="off"
            placeholder="For example: Finance team"
            onChange={(event) => setLabel(event.target.value)}
          />
          <div className="sm:pt-[26px]">
            <Button
              type="submit"
              variant="primary"
              loading={add.isPending}
              disabled={email.trim() === "" || room <= 0}
            >
              <Plus aria-hidden />
              Save
            </Button>
          </div>
        </form>
      ) : (
        <form onSubmit={addMany} className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor="paste-people" className="block text-[13px] font-medium">
              Paste several addresses
            </label>
            <BareTextArea
              id="paste-people"
              rows={4}
              value={pasted}
              placeholder={"ann@company.com\nbob@company.com, finance@company.com"}
              onChange={(event) => setPasted(event.target.value)}
            />
            <p className="text-[12.5px] text-subtle">
              Put them on separate lines or separate them with commas. Copying from your mail
              program works too.
            </p>
          </div>
          {pasted.trim() !== "" && (
            <p className="text-[13px]" aria-live="polite">
              <b>
                {fresh.length} new {fresh.length === 1 ? "address" : "addresses"}
              </b>{" "}
              to save
              {already > 0 && <span className="text-muted">, {already} already saved</span>}
              {parsed.invalid.length > 0 && (
                <span className="text-danger">
                  , not an address: {parsed.invalid.slice(0, 3).join(", ")}
                  {parsed.invalid.length > 3 && "…"}
                </span>
              )}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" variant="primary" loading={busy} disabled={fresh.length === 0}>
              <Plus aria-hidden />
              {fresh.length > 0 ? `Save ${fresh.length}` : "Save"}
            </Button>
            <Button variant="ghost" onClick={() => setSeveral(false)}>
              Back to one address
            </Button>
          </div>
        </form>
      )}

      {!several && (
        <button
          type="button"
          onClick={() => {
            setSeveral(true);
            setReport(null);
          }}
          className="text-[13px] text-accent underline-offset-2 hover:underline"
        >
          Have a list? Paste several addresses at once
        </button>
      )}
      {room <= 0 && (
        <Notice tone="warn" title="Your list is full">
          You can keep up to {LIMIT} addresses. Remove one to add another.
        </Notice>
      )}
      {add.error && !busy && (
        <Notice tone="error" title="That address was not saved">
          {asApiError(add.error).message}
        </Notice>
      )}
      {failure && (
        <Notice tone="error" title="Some addresses were not saved">
          {failure}
        </Notice>
      )}
      {report && (
        <p role="status" className="text-[13px] text-success">
          {report}
        </p>
      )}
    </div>
  );
}

// ── One person ───────────────────────────────────────────────────────────────

function Row({ item }: { item: SavedRecipient }) {
  const remove = useDeleteRecipient();
  const [confirming, setConfirming] = useState(false);
  const name = item.label || item.email;

  return (
    <li className="flex items-center gap-3 px-5 py-3">
      <span
        aria-hidden
        className="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[12px] font-semibold text-muted"
      >
        {initials(name)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-medium">{name}</p>
        {item.label && <p className="truncate text-[13px] text-muted">{item.email}</p>}
      </div>
      {confirming ? (
        <div className="flex shrink-0 items-center gap-1">
          <span className="mr-1 hidden text-[13px] text-muted sm:inline">Remove?</span>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            Keep
          </Button>
          <Button
            size="sm"
            className="text-danger hover:bg-danger-soft"
            loading={remove.isPending}
            onClick={() => remove.mutate(item.id)}
          >
            Remove
          </Button>
        </div>
      ) : (
        <Button
          size="icon"
          variant="ghost"
          aria-label={`Remove ${item.email}`}
          title="Remove"
          onClick={() => setConfirming(true)}
        >
          <Trash2 aria-hidden className="size-4" />
        </Button>
      )}
    </li>
  );
}
