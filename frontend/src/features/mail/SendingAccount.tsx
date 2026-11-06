import { CheckCircle2, ChevronDown, Mail, Send } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { SelectField, TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { asApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/cn";
import { timeAgo } from "../../lib/format";
import { friendlyMailError, isEmail } from "./addresses";
import { PRESETS, presetFor } from "./presets";
import { useClearMail, useSaveMail, useSendTestMail, type MailSettings } from "./queries";

/**
 * The account emails are sent from: for administrators. It asks for the few things a person
 * knows (which mail service, an address, a password) and keeps the server details out of the way
 * under "Advanced", because most people never need them.
 */
export function SendingAccount({ mail }: { mail: MailSettings }) {
  return (
    <div className="space-y-5">
      <Form key={`${mail.source}-${mail.updated_at}`} mail={mail} />
    </div>
  );
}

function Form({ mail }: { mail: MailSettings }) {
  const { user } = useAuth();
  const save = useSaveMail();
  const clear = useClearMail();
  const test = useSendTestMail();
  const saved = mail.configured;
  const [provider, setProvider] = useState(presetFor(mail.host).id);
  const [email, setEmail] = useState(mail.from_address);
  const [password, setPassword] = useState("");
  const [host, setHost] = useState(mail.host);
  const [port, setPort] = useState(String(mail.port));
  const [security, setSecurity] = useState(mail.security);
  // Left empty, these follow the email address above, which is right for nearly everyone.
  const [loginName, setLoginName] = useState(
    mail.username && mail.username !== mail.from_address ? mail.username : "",
  );
  const [confirmingClear, setConfirmingClear] = useState(false);
  const preset = PRESETS.find((p) => p.id === provider)!;
  const custom = provider === "other";
  const portNumber = Number(port);
  const valid =
    isEmail(email) && host.trim() !== "" && Number.isInteger(portNumber) && portNumber > 0;
  // A password is needed to sign in, unless the account was already saved with one or the relay is open.
  const needsPassword = !mail.has_password && !password && security !== "none";
  const problem = save.error ? asApiError(save.error).message : null;

  function choose(id: string) {
    const next = PRESETS.find((p) => p.id === id)!;
    setProvider(id);
    if (next.host) {
      setHost(next.host);
      setPort(String(next.port));
      setSecurity(next.security);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    test.reset();
    save.mutate(
      {
        host: host.trim(),
        port: portNumber,
        security,
        username: loginName.trim() || email.trim(),
        // Empty means "keep the saved one": the password is never sent back to this page.
        // Gmail shows its app passwords in groups of four letters; the spaces are not part of it.
        ...(password
          ? { password: provider === "gmail" ? password.replace(/\s+/g, "") : password }
          : {}),
        from_address: email.trim(),
      },
      {
        onSuccess: () => {
          setPassword("");
          // Prove it works straight away, by sending a message to the person who set it up.
          test.mutate(user?.email ?? "");
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader
        title={
          <>
            <Mail aria-hidden className="size-4 text-accent" />
            Sending account
          </>
        }
        description="Pick the mail service and sign in once. Reports and alerts are then emailed from this address."
        aside={
          saved && mail.source === "app" && mail.updated_at ? (
            <span className="text-[12.5px] text-subtle">Saved {timeAgo(mail.updated_at)}</span>
          ) : undefined
        }
      />
      <form onSubmit={submit} noValidate className="divide-y divide-border">
        <Step number={1} title="Choose your email service">
          <div role="radiogroup" aria-label="Email service" className="grid gap-3 sm:grid-cols-3">
            {PRESETS.map((option) => (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={provider === option.id}
                onClick={() => choose(option.id)}
                className={cn(
                  "rounded-lg border p-4 text-left transition-colors focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none",
                  provider === option.id
                    ? "border-accent/60 bg-accent-soft"
                    : "border-border hover:border-border-strong hover:bg-surface-2/50",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-[14px] font-semibold">{option.label}</span>
                  {provider === option.id && (
                    <CheckCircle2 aria-hidden className="size-4 text-accent" />
                  )}
                </span>
                <span className="mt-1 block text-[12.5px] text-muted">{option.summary}</span>
              </button>
            ))}
          </div>
        </Step>

        <Step number={2} title="Sign in">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Your email address"
              type="email"
              autoComplete="off"
              value={email}
              placeholder="you@company.com"
              hint="Emails will come from this address."
              error={
                email.trim() !== "" && !isEmail(email)
                  ? "That doesn't look like an email address."
                  : undefined
              }
              onChange={(event) => setEmail(event.target.value)}
            />
            <TextField
              label={provider === "gmail" ? "App password" : "Password"}
              type="password"
              autoComplete="new-password"
              value={password}
              placeholder={mail.has_password ? "Saved. Type to replace it." : ""}
              hint={
                mail.vault_ready
                  ? provider === "gmail"
                    ? "Not your normal Gmail password. See how to get one below."
                    : undefined
                  : "To keep a password, the server needs CONNECTION_ENCRYPTION_KEY in its .env file."
              }
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          {provider === "gmail" && <GmailHelp />}
          {preset.help && provider !== "gmail" && (
            <p className="text-[13px] text-muted">{preset.help}</p>
          )}
        </Step>

        <details open={custom} className="group px-5 py-4 sm:px-6">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-[13.5px] font-medium text-muted hover:text-fg">
            <ChevronDown
              aria-hidden
              className="size-4 transition-transform group-open:rotate-180"
            />
            Advanced settings
            <span className="font-normal text-subtle">
              {custom ? "(needed for this service)" : "(usually not needed)"}
            </span>
          </summary>
          <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_8rem_13rem]">
            <TextField
              label="Mail server"
              value={host}
              placeholder="smtp.example.com"
              onChange={(event) => setHost(event.target.value)}
            />
            <TextField
              label="Port"
              inputMode="numeric"
              value={port}
              onChange={(event) => setPort(event.target.value.replace(/\D/g, "").slice(0, 5))}
            />
            <SelectField
              label="Security"
              value={security}
              options={[
                { value: "starttls", label: "STARTTLS (587)" },
                { value: "ssl", label: "SSL (465)" },
                { value: "none", label: "None (trusted relay)" },
              ]}
              onChange={(event) => setSecurity(event.target.value as MailSettings["security"])}
            />
          </div>
          <div className="mt-4 max-w-md">
            <TextField
              label="Sign-in name"
              value={loginName}
              placeholder={email || "Same as your email address"}
              hint="Only fill this in if your service signs you in with something other than your email address."
              onChange={(event) => setLoginName(event.target.value)}
            />
          </div>
        </details>

        {(problem || (test.data && !test.data.ok) || test.error) && (
          <div className="px-5 py-4 sm:px-6">
            <Notice
              tone="error"
              title={problem ? "Your settings were not saved" : "The test email did not go out"}
            >
              {friendlyMailError(
                problem ?? test.data?.message ?? asApiError(test.error).message,
                provider,
              )}
            </Notice>
          </div>
        )}
        {test.data?.ok && (
          <div className="px-5 py-4 sm:px-6">
            <Notice title="Email is working">
              Your settings are saved and a test email was sent to {test.data.sent_to}. Check that
              inbox, and the spam folder if you don't see it.
            </Notice>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 bg-surface-2/40 px-5 py-4 sm:px-6">
          <Button
            type="submit"
            variant="primary"
            loading={save.isPending || test.isPending}
            disabled={!valid || needsPassword}
          >
            <Send aria-hidden />
            {saved ? "Save and send a test" : "Connect and send a test"}
          </Button>
          <span className="min-w-0 flex-1 text-[12.5px] text-subtle">
            We send one test email to {user?.email ?? "you"} so you know it works.
          </span>
          {mail.source === "app" &&
            (confirmingClear ? (
              <span className="flex items-center gap-1.5 text-[13px]">
                <span className="text-muted">Stop sending email?</span>
                <Button variant="ghost" size="sm" onClick={() => setConfirmingClear(false)}>
                  Keep it
                </Button>
                <Button
                  size="sm"
                  className="text-danger hover:bg-danger-soft"
                  loading={clear.isPending}
                  onClick={() =>
                    clear.mutate(undefined, { onSuccess: () => setConfirmingClear(false) })
                  }
                >
                  Remove
                </Button>
              </span>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setConfirmingClear(true)}>
                Remove this account
              </Button>
            ))}
        </div>
      </form>
    </Card>
  );
}

function Step({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return (
    <section className="space-y-4 px-5 py-5 sm:px-6">
      <h3 className="flex items-center gap-2.5 text-[14.5px] font-semibold">
        <span
          aria-hidden
          className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent"
        >
          {number}
        </span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function GmailHelp() {
  return (
    <details className="group rounded-lg border border-border bg-surface-2/40 px-4 py-3">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-[13.5px] font-medium">
        <ChevronDown aria-hidden className="size-4 transition-transform group-open:rotate-180" />
        How do I get a Gmail app password?
      </summary>
      <ol className="mt-3 list-decimal space-y-1.5 pl-9 text-[13px] text-muted">
        <li>Sign in to your Google account and turn on 2-Step Verification.</li>
        <li>
          Open <b className="font-medium text-fg">myaccount.google.com/apppasswords</b>.
        </li>
        <li>Type a name such as “Eye of Ender” and click Create.</li>
        <li>Copy the 16-letter code Google shows and paste it into the box above.</li>
      </ol>
    </details>
  );
}
