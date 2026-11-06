import {
  Check,
  Copy,
  KeyRound,
  MailPlus,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  UserCheck,
  UserRoundX,
  UsersRound,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type FormEvent } from "react";

import { PageHeader } from "../../components/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { PasswordField, SelectField, TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { StatTile } from "../../components/ui/StatTile";
import { Badge, StatusLabel } from "../../components/ui/Status";
import { asApiError, type Role, type User } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/cn";
import { initials, timeAgo } from "../../lib/format";
import { MIN_PASSWORD, PASSWORD_HINT } from "../auth/rules";
import { InvitePanel, PendingInvites } from "./Invites";
import { useCreateUser, useUpdateUser, useUsers } from "./queries";
import { ROLE_HELP, ROLE_LABEL, ROLE_OPTIONS } from "./roles";

const EASE = [0.16, 1, 0.3, 1] as const;

// Fixed columns on wider screens, so every row lines up with the headings; stacked on phones.
const ROW_COLUMNS =
  "sm:grid-cols-[minmax(0,1fr)_8rem_9.5rem] lg:grid-cols-[minmax(0,1fr)_8rem_10rem_14rem]";

const ROLE_FILTER = [{ value: "", label: "All roles" }, ...ROLE_OPTIONS];

export function UsersPage() {
  const users = useUsers();
  const [adding, setAdding] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("");

  const all = users.data ?? [];
  const needle = query.trim().toLowerCase();
  const shown = all.filter(
    (user) =>
      (!role || user.role === role) &&
      (!needle ||
        user.full_name.toLowerCase().includes(needle) ||
        user.email.toLowerCase().includes(needle)),
  );
  const filtered = Boolean(needle || role);

  return (
    <>
      <PageHeader
        title="Users"
        description="Everyone who can sign in. Invite people by email, so they choose their own password."
        actions={
          !adding &&
          !inviting && (
            <div className="flex gap-2">
              <Button onClick={() => setAdding(true)}>
                <Plus aria-hidden />
                Add with a password
              </Button>
              <Button variant="primary" onClick={() => setInviting(true)}>
                <MailPlus aria-hidden />
                Invite people
              </Button>
            </div>
          )
        }
      />

      <div className="space-y-6">
        <AnimatePresence initial={false}>
          {inviting && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: EASE }}
              className="overflow-hidden"
            >
              <InvitePanel onDone={() => setInviting(false)} />
            </motion.div>
          )}
          {adding && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: EASE }}
              className="overflow-hidden"
            >
              <AddUserForm onDone={() => setAdding(false)} />
            </motion.div>
          )}
        </AnimatePresence>

        <PendingInvites />

        {all.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-3">
            <StatTile label="People" icon={UsersRound} value={all.length} />
            <StatTile
              label="Active"
              icon={UserCheck}
              tone="ok"
              value={all.filter((user) => user.is_active).length}
              hint={`${all.filter((user) => !user.is_active).length} turned off`}
            />
            <StatTile
              label="Admins"
              icon={ShieldCheck}
              value={all.filter((user) => user.role === "admin").length}
            />
          </div>
        )}

        <Card className="overflow-hidden rounded-xl">
          {all.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3">
              <label className="relative block min-w-56 flex-1">
                <span className="sr-only">Search people</span>
                <Search
                  aria-hidden
                  className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle"
                />
                <input
                  type="search"
                  placeholder="Search by name or email"
                  maxLength={100}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="h-9 w-full rounded-lg border border-border bg-bg pr-3 pl-9 text-[14px] placeholder:text-subtle hover:border-border-strong focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
                />
              </label>
              <div className="w-40">
                <SelectField
                  hideLabel
                  label="Role"
                  options={ROLE_FILTER}
                  value={role}
                  onChange={(event) => setRole(event.target.value)}
                />
              </div>
            </div>
          )}
          {users.isPending ? (
            <div className="space-y-3 p-5">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : users.isError ? (
            <div className="p-5">
              <Notice tone="error" title="Could not load users">
                {users.error.message}
              </Notice>
            </div>
          ) : all.length === 0 ? (
            <EmptyState icon={UsersRound} title="No users yet" />
          ) : shown.length === 0 ? (
            <p className="px-5 py-10 text-center text-[13.5px] text-muted">
              {filtered ? "Nobody matches that search." : "No users."}
            </p>
          ) : (
            <>
              <div
                aria-hidden
                className={cn(
                  "hidden gap-3 border-b border-border bg-surface-2/40 px-5 py-2 lg:grid",
                  ROW_COLUMNS,
                  "text-[11px] font-semibold tracking-wide text-subtle uppercase",
                )}
              >
                <span>User</span>
                <span>Role</span>
                <span>Status</span>
                <span className="text-right">Actions</span>
              </div>
              <ul className="divide-y divide-border">
                {shown.map((user) => (
                  <UserRow key={user.id} user={user} />
                ))}
              </ul>
              <p className="border-t border-border bg-surface-2/30 px-5 py-2.5 text-[12.5px] text-muted">
                {filtered ? `${shown.length} of ${all.length} people` : `${all.length} people`}
              </p>
            </>
          )}
        </Card>
      </div>
    </>
  );
}

function generatePassword(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(12));
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function AddUserForm({ onDone }: { onDone: () => void }) {
  const create = useCreateUser();
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    role: "viewer" as Role,
    password: "",
  });
  const [touched, setTouched] = useState(false);
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);
  const error = create.error ? asApiError(create.error) : null;

  const problems = {
    full_name: form.full_name.trim() ? undefined : "Enter a name.",
    email: /\S+@\S+\.\S+/.test(form.email) ? undefined : "Enter a valid email address.",
    password:
      form.password.length >= MIN_PASSWORD ? undefined : `Use at least ${MIN_PASSWORD} characters.`,
  };
  const shown = (field: keyof typeof problems) =>
    (touched ? problems[field] : undefined) ?? error?.fieldErrors[field];

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (Object.values(problems).some(Boolean)) return;
    create.mutate(form, {
      onSuccess: () => {
        setCreated({ email: form.email.trim().toLowerCase(), password: form.password });
        setForm({ full_name: "", email: "", role: "viewer", password: "" });
        setTouched(false);
      },
    });
  }

  const update = (field: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: event.target.value }));

  return (
    <Card className="overflow-hidden rounded-xl">
      <CardHeader
        title="Add a user"
        description="They sign in with this email and password, and can change the password on their Account page."
      />
      <form onSubmit={submit} noValidate>
        <div className="space-y-4 p-5">
          {created && (
            <Notice
              title="User added"
              action={
                <div className="flex items-center gap-2">
                  <CopyDetails text={`${created.email} / ${created.password}`} />
                  <Button size="sm" onClick={onDone}>
                    Done
                  </Button>
                </div>
              }
            >
              Share these sign-in details with them privately:{" "}
              <code className="font-mono text-fg">{created.email}</code> /{" "}
              <code className="font-mono text-fg">{created.password}</code>
            </Notice>
          )}
          {error && error.code !== "validation_error" && (
            <Notice tone="error" title="User not added">
              {error.message}
            </Notice>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Full name"
              autoComplete="off"
              value={form.full_name}
              onChange={update("full_name")}
              error={shown("full_name")}
            />
            <TextField
              label="Email"
              type="email"
              autoComplete="off"
              value={form.email}
              onChange={update("email")}
              error={shown("email")}
            />
            <div className="space-y-1.5">
              <SelectField
                label="Role"
                options={ROLE_OPTIONS}
                value={form.role}
                onChange={update("role")}
              />
              <p className="text-[12.5px] text-subtle">{ROLE_HELP[form.role]}</p>
            </div>
            <div className="space-y-1.5">
              <PasswordField
                label="Password"
                autoComplete="new-password"
                value={form.password}
                onChange={update("password")}
                error={shown("password")}
                hint={PASSWORD_HINT}
              />
              <button
                type="button"
                onClick={() => setForm((current) => ({ ...current, password: generatePassword() }))}
                className="inline-flex items-center gap-1.5 text-[13px] font-medium text-accent underline-offset-4 hover:underline"
              >
                <Sparkles aria-hidden className="size-3.5" />
                Generate a strong password
              </button>
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-border bg-surface-2/40 px-5 py-3.5">
          <Button onClick={onDone}>Cancel</Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Add user
          </Button>
        </div>
      </form>
    </Card>
  );
}

function CopyDetails({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // Clipboard access can be blocked; the details are still selectable.
        }
      }}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

function UserRow({ user }: { user: User }) {
  const { user: me } = useAuth();
  const update = useUpdateUser();
  const [settingPassword, setSettingPassword] = useState(false);
  const [password, setPassword] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const isMe = me?.id === user.id;
  const error = update.error ? asApiError(update.error) : null;

  function change(changeSet: Parameters<typeof update.mutate>[0]["change"], message: string) {
    setSaved(null);
    update.mutate(
      { id: user.id, change: changeSet },
      {
        onSuccess: () => {
          setSaved(message);
          setSettingPassword(false);
          setPassword("");
        },
      },
    );
  }

  return (
    <li className="px-5 py-4 transition-colors hover:bg-surface-2/30">
      <div className={cn("grid grid-cols-1 gap-3 sm:items-center", ROW_COLUMNS)}>
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold ring-1 ring-border",
              user.is_active ? "bg-accent-soft text-accent" : "bg-surface-2 text-subtle",
            )}
          >
            {initials(user.full_name)}
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium">
              {user.full_name}
              {isMe && <span className="ml-1.5 font-normal text-subtle">(you)</span>}
            </p>
            <p className="truncate text-[13px] text-muted">{user.email}</p>
          </div>
        </div>

        <div>
          {isMe ? (
            <Badge tone="accent">{ROLE_LABEL[user.role]}</Badge>
          ) : (
            <SelectField
              label={`Role for ${user.full_name}`}
              hideLabel
              options={ROLE_OPTIONS}
              value={user.role}
              disabled={update.isPending}
              onChange={(event) =>
                change(
                  { role: event.target.value as Role },
                  `Role changed to ${ROLE_LABEL[event.target.value as Role]}.`,
                )
              }
              className="h-8 text-[13px]"
            />
          )}
        </div>

        <div className="text-[13px]">
          <StatusLabel tone={user.is_active ? "ok" : "neutral"}>
            {user.is_active ? "Active" : "Turned off"}
          </StatusLabel>
          <p className="mt-0.5 text-subtle">
            {user.last_login_at ? `Signed in ${timeAgo(user.last_login_at)}` : "Never signed in"}
          </p>
        </div>

        <div className="flex min-h-8 gap-1 sm:col-span-3 sm:justify-end lg:col-span-1">
          {!isMe && (
            <Button
              variant="ghost"
              size="sm"
              aria-expanded={settingPassword}
              onClick={() => setSettingPassword((open) => !open)}
            >
              <KeyRound aria-hidden />
              Set password
            </Button>
          )}
          {!isMe && (
            <Button
              variant="ghost"
              size="sm"
              className={user.is_active ? "text-danger hover:bg-danger-soft" : undefined}
              disabled={update.isPending}
              onClick={() =>
                change(
                  { is_active: !user.is_active },
                  user.is_active ? "Turned off and signed out everywhere." : "Turned back on.",
                )
              }
            >
              {user.is_active && <UserRoundX aria-hidden />}
              {user.is_active ? "Turn off" : "Turn on"}
            </Button>
          )}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {settingPassword && (
          <motion.form
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: EASE }}
            className="overflow-hidden"
            onSubmit={(event) => {
              event.preventDefault();
              if (password.length >= MIN_PASSWORD) {
                change({ password }, "Password set. They were signed out everywhere.");
              }
            }}
          >
            <div className="flex flex-wrap items-end gap-3 pt-3 sm:pl-12">
              <div className="w-full max-w-xs">
                <PasswordField
                  label={`New password for ${user.full_name}`}
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  hint={PASSWORD_HINT}
                />
              </div>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                className="mb-6"
                loading={update.isPending}
                disabled={password.length < MIN_PASSWORD}
              >
                Save password
              </Button>
            </div>
          </motion.form>
        )}
      </AnimatePresence>

      {error && (
        <Notice tone="error" title="Change not saved" className="mt-3 sm:ml-12">
          {error.message}
        </Notice>
      )}
      {saved && !error && (
        <p role="status" className="mt-2 text-[13px] text-muted sm:pl-12">
          {saved}
        </p>
      )}
    </li>
  );
}
