import {
  Check,
  ChevronDown,
  CircleCheck,
  Copy,
  Database,
  History,
  KeyRound,
  Lock,
  MessageSquare,
  Pencil,
  Plus,
  Server,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router";

import { PageHeader } from "../../components/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { PasswordField, SelectField, TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { Skeleton } from "../../components/ui/Skeleton";
import { StatTile } from "../../components/ui/StatTile";
import { Badge, StatusLabel } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { timeAgo } from "../../lib/format";
import { useCreateSpace } from "../spaces/queries";
import {
  SSL_OPTIONS,
  STATUS_LABEL,
  STATUS_TONE,
  changesOf,
  createBody,
  describeEvent,
  emptyForm,
  formFromConnection,
  problemsIn,
  provisionBody,
} from "./connections";
import {
  useAuditTrail,
  useConnections,
  useCreateConnection,
  useDeleteConnection,
  useMakeReadOnly,
  useProvisionConnection,
  useTestConnection,
  useUpdateConnection,
} from "./queries";
import type { Connection, ConnectionForm, ConnectionTest } from "./types";

const EASE = [0.16, 1, 0.3, 1] as const;

const SSL_SHORT: Record<string, string> = {
  "verify-full": "Encrypted, verified",
  "verify-ca": "Encrypted, certificate checked",
  require: "Encrypted",
  disable: "Not encrypted",
};

const READ_ONLY_LOGIN = `CREATE ROLE eoe_reader LOGIN PASSWORD '<a long random password>';
GRANT CONNECT ON DATABASE sales TO eoe_reader;
GRANT USAGE ON SCHEMA public TO eoe_reader;
GRANT SELECT ON public.orders, public.customers TO eoe_reader;  -- only what should be analysed`;

export function ConnectionsPage() {
  const connections = useConnections();
  const [adding, setAdding] = useState(false);
  const [activity, setActivity] = useState(false);
  const [made, setMade] = useState<ConnectionTest | null>(null);

  return (
    <>
      <PageHeader
        title="Connections"
        description="Databases the assistant can answer questions from. Only logins that can read are accepted: the database itself is the real safety wall."
        actions={
          !adding && (
            <Button variant="primary" onClick={() => setAdding(true)}>
              <Plus aria-hidden />
              Add connection
            </Button>
          )
        }
      />

      <div className="space-y-5">
        <AnimatePresence initial={false}>
          {adding && (
            <Reveal key="add">
              <ConnectionFormCard
                onDone={(result) => {
                  setAdding(false);
                  if (result) setMade(result);
                }}
              />
            </Reveal>
          )}
        </AnimatePresence>

        {made && <MadeNote result={made} onClose={() => setMade(null)} />}

        {connections.data && connections.data.length > 0 && <Summary list={connections.data} />}

        {connections.isPending ? (
          <div className="space-y-4">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-40 rounded-xl" />
            ))}
          </div>
        ) : connections.isError ? (
          <Notice tone="error" title="Could not load connections">
            {connections.error.message}
          </Notice>
        ) : connections.data.length === 0 ? (
          !adding && (
            <Card className="rounded-xl">
              <EmptyState icon={Database} title="No connections yet">
                Add one to let a space use the tables of a PostgreSQL database.
              </EmptyState>
            </Card>
          )
        ) : (
          <ul className="space-y-4">
            {connections.data.map((connection) => (
              <ConnectionRow key={connection.id} connection={connection} />
            ))}
          </ul>
        )}

        <Card className="rounded-xl">
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded-lg px-5 py-4 focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none [&::-webkit-details-marker]:hidden">
              <span className="flex min-w-0 items-start gap-3.5">
                <span
                  aria-hidden
                  className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted ring-1 ring-border"
                >
                  <KeyRound className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[15px] font-semibold">
                    A login that can only read
                  </span>
                  <span className="block text-[13px] text-muted">
                    Run this on the database server, then use that login here. A login that can
                    change data, create objects or is a superuser is refused.
                  </span>
                </span>
              </span>
              <ChevronDown
                aria-hidden
                className="size-4 shrink-0 text-subtle transition-transform group-open:rotate-180"
              />
            </summary>
            <div className="relative border-t border-border">
              <CopyButton text={READ_ONLY_LOGIN} />
              <pre className="overflow-x-auto p-5 pr-24 font-mono text-[12.5px] leading-6 text-muted">
                {READ_ONLY_LOGIN}
              </pre>
            </div>
          </details>
        </Card>

        <Card className="rounded-xl">
          <CardHeader
            className={activity ? undefined : "border-b-0"}
            title="Activity"
            description="Who created, changed, tested or used a connection. Passwords are never recorded."
            aside={
              <Button size="sm" variant="ghost" onClick={() => setActivity((value) => !value)}>
                <History aria-hidden />
                {activity ? "Hide" : "Show"}
              </Button>
            }
          />
          {activity && <Activity />}
        </Card>
      </div>
    </>
  );
}

/** How many connections work, and how many need a look. */
function Summary({ list }: { list: Connection[] }) {
  const working = list.filter((c) => c.status === "ok").length;
  const attention = list.filter((c) => c.status === "failed" || c.status === "unsafe").length;
  const untested = list.filter((c) => c.status === "untested").length;
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <StatTile label="Connections" icon={Database} value={list.length} />
      <StatTile
        label="Working"
        icon={CircleCheck}
        tone={working > 0 ? "ok" : "default"}
        value={working}
        hint={untested > 0 ? `${untested} not tested yet` : undefined}
      />
      <StatTile
        label="Need attention"
        icon={TriangleAlert}
        tone={attention > 0 ? "danger" : "default"}
        value={attention}
        hint={attention > 0 ? "Failed or not read-only" : "Nothing to fix"}
      />
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      variant="ghost"
      className="absolute top-3 right-3"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // Clipboard access can be blocked; the text is still selectable.
        }
      }}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

function Reveal({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.25, ease: EASE }}
      className="overflow-hidden"
    >
      {children}
    </motion.div>
  );
}

function Activity() {
  const events = useAuditTrail(true);
  if (events.isPending) return <Skeleton className="m-5 h-24" />;
  if (events.isError) {
    return (
      <div className="p-5">
        <Notice tone="error" title="Could not load the activity">
          {events.error.message}
        </Notice>
      </div>
    );
  }
  if (events.data.length === 0) return <p className="p-5 text-[13px] text-muted">Nothing yet.</p>;
  return (
    <ul className="divide-y divide-border">
      {events.data.map((event) => (
        <li key={event.id} className="flex items-baseline justify-between gap-4 px-5 py-2.5">
          <span className="text-[13px]">{describeEvent(event)}</span>
          <span className="shrink-0 text-[12.5px] text-subtle">{timeAgo(event.created_at)}</span>
        </li>
      ))}
    </ul>
  );
}

// ── One connection ───────────────────────────────────────────────────────────

function ConnectionRow({ connection }: { connection: Connection }) {
  const [editing, setEditing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [fixing, setFixing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<ConnectionTest | null>(null);
  const test = useTestConnection();
  const remove = useDeleteConnection();
  const testError = test.error ? asApiError(test.error) : null;
  const removeError = remove.error ? asApiError(remove.error) : null;

  return (
    <li>
      <Card className="overflow-hidden rounded-xl">
        <div className="flex flex-wrap items-start gap-x-4 gap-y-3 p-5">
          <span
            aria-hidden
            className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-muted ring-1 ring-border"
          >
            <Database className="size-5" />
          </span>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h3 className="text-[16px] font-semibold">{connection.name}</h3>
              <StatusLabel tone={STATUS_TONE[connection.status]}>
                {STATUS_LABEL[connection.status]}
              </StatusLabel>
            </div>
            <p className="truncate font-mono text-[12.5px] text-subtle">
              {connection.host}:{connection.port}/{connection.database}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            {connection.status === "unsafe" && (
              <Button size="sm" variant="primary" onClick={() => setFixing((value) => !value)}>
                <ShieldCheck aria-hidden />
                Make it read-only
              </Button>
            )}
            {connection.status === "ok" && (
              <Button size="sm" variant="primary" onClick={() => setStarting((value) => !value)}>
                <MessageSquare aria-hidden />
                Chat with it
              </Button>
            )}
            <Button
              size="sm"
              loading={test.isPending}
              onClick={() =>
                test.mutate(connection.id, { onSuccess: (outcome) => setResult(outcome) })
              }
            >
              <Zap aria-hidden />
              Test
            </Button>
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Edit ${connection.name}`}
              title="Edit"
              onClick={() => setEditing((value) => !value)}
            >
              <Pencil aria-hidden />
            </Button>
            {confirming ? (
              <>
                <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                  Keep
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  className="bg-danger hover:bg-danger/90"
                  loading={remove.isPending}
                  onClick={() =>
                    remove.mutate(connection.id, { onSettled: () => setConfirming(false) })
                  }
                >
                  Delete
                </Button>
              </>
            ) : (
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Delete ${connection.name}`}
                title="Delete"
                onClick={() => setConfirming(true)}
              >
                <Trash2 aria-hidden />
              </Button>
            )}
          </div>
        </div>

        {(connection.status === "failed" || connection.status === "unsafe") &&
          connection.status_detail && (
            <p className="mx-5 mb-4 rounded-md bg-danger-soft px-3 py-2 text-[12.5px] text-fg">
              {connection.status_detail}
            </p>
          )}

        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-border bg-surface-2/30 px-5 py-4 sm:grid-cols-3 lg:grid-cols-5">
          <Fact label="Login">
            <span className="font-mono">{connection.username}</span>
          </Fact>
          <Fact label="Encryption">
            <span className="inline-flex items-center gap-1.5">
              <Lock aria-hidden className="size-3.5 text-subtle" />
              {SSL_SHORT[connection.ssl_mode] ?? connection.ssl_mode}
            </span>
          </Fact>
          <Fact label="Server">
            {connection.server_version ? `PostgreSQL ${connection.server_version}` : "Unknown"}
          </Fact>
          <Fact label="Last tested">
            {connection.tested_at ? timeAgo(connection.tested_at) : "Never"}
          </Fact>
          <Fact label="AI sees result rows">
            <Badge tone={connection.share_results_with_ai ? "warn" : "neutral"}>
              {connection.share_results_with_ai ? "Yes" : "No"}
            </Badge>
          </Fact>
        </dl>

        <div className="space-y-3 px-5 pb-5 empty:hidden">
          {testError && (
            <Notice tone="error" title="Could not test the connection" className="mt-4">
              {testError.message}
            </Notice>
          )}
          {removeError && (
            <Notice tone="error" title="Could not delete the connection" className="mt-4">
              {removeError.message}
            </Notice>
          )}
          {result && <TestResult result={result} onClose={() => setResult(null)} />}

          <AnimatePresence initial={false}>
            {fixing && (
              <Reveal key="fix">
                <div className="pt-4">
                  <MakeReadOnlyPanel
                    connection={connection}
                    onCancel={() => setFixing(false)}
                    onDone={(outcome) => {
                      setFixing(false);
                      setResult(outcome);
                    }}
                  />
                </div>
              </Reveal>
            )}
            {starting && (
              <Reveal key="chat">
                <div className="pt-4">
                  <StartChat connection={connection} onCancel={() => setStarting(false)} />
                </div>
              </Reveal>
            )}
            {editing && (
              <Reveal key="edit">
                <div className="pt-4">
                  <ConnectionFormCard
                    connection={connection}
                    onDone={() => {
                      setEditing(false);
                      // A result from before the change says nothing about the connection now.
                      setResult(null);
                      test.reset();
                    }}
                  />
                </div>
              </Reveal>
            )}
          </AnimatePresence>
        </div>
      </Card>
    </li>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 space-y-1">
      <dt className="text-[11px] font-semibold tracking-wide text-subtle uppercase">{label}</dt>
      <dd className="truncate text-[13px]">{children}</dd>
    </div>
  );
}

/**
 * The short way to chat with a database: make a space for it, then pick which of the tables the
 * login can read the space may use. A space is where the tables, rules and joins for a topic
 * live, and it shows up in the chat's space switcher like any other.
 */
function StartChat({ connection, onCancel }: { connection: Connection; onCancel: () => void }) {
  const create = useCreateSpace();
  const navigate = useNavigate();
  const [name, setName] = useState(connection.name);
  const error = create.error ? asApiError(create.error) : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    create.mutate(
      { name: name.trim(), description: `Questions about the ${connection.database} database` },
      { onSuccess: (space) => void navigate(`/spaces/${space.id}?connection=${connection.id}`) },
    );
  }

  return (
    <Card className="bg-surface-2/40">
      <CardHeader
        title="Chat with this database"
        description="This makes a space for it. Next you choose which tables the space may use, and only those are ever available to the chat."
      />
      <form onSubmit={submit} noValidate className="space-y-4 p-5">
        {error && (
          <Notice tone="error" title="Could not create the space">
            {error.message}
          </Notice>
        )}
        <TextField
          label="Space name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          error={name.trim() ? undefined : "Give the space a name."}
        />
        <div className="flex justify-end gap-2">
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Create space and choose tables
          </Button>
        </div>
      </form>
    </Card>
  );
}

/**
 * A login that can do more than read is never used for questions. This uses it once to create a
 * login that can only SELECT, switches the connection to that one, and replaces the saved
 * password, so the powerful one is no longer stored.
 */
function MakeReadOnlyPanel({
  connection,
  onCancel,
  onDone,
}: {
  connection: Connection;
  onCancel: () => void;
  onDone: (result: ConnectionTest) => void;
}) {
  const fix = useMakeReadOnly();
  const error = fix.error ? asApiError(fix.error) : null;
  return (
    <Card className="bg-surface-2/40">
      <CardHeader
        title="Switch to a read-only login"
        description={`${connection.username} can do more than read, so it can't be used for questions. It can still be used once, right now, to make a new login for this connection.`}
      />
      <div className="space-y-4 p-5">
        {error && (
          <Notice tone="error" title="Could not make the read-only login">
            {error.message}
          </Notice>
        )}
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted">
          <li>A new login is created that can only read tables (no changes, no new objects).</li>
          <li>
            This connection switches to it, and {connection.username}&apos;s password is replaced,
            so it is no longer stored here.
          </li>
          <li>Nothing in your tables, and no other login, is changed.</li>
        </ul>
        <div className="flex justify-end gap-2">
          <Button onClick={onCancel}>Cancel</Button>
          <Button
            variant="primary"
            loading={fix.isPending}
            onClick={() => fix.mutate(connection.id, { onSuccess: onDone })}
          >
            Make it read-only
          </Button>
        </div>
      </div>
    </Card>
  );
}

function MadeNote({ result, onClose }: { result: ConnectionTest; onClose: () => void }) {
  return (
    <Notice
      tone={result.ok ? "info" : "warn"}
      title={
        result.ok
          ? `Connected with a new read-only login (${result.connection.username})`
          : "The login was made, but the test found a problem"
      }
      action={
        <Button size="sm" variant="ghost" onClick={onClose}>
          Dismiss
        </Button>
      }
    >
      <p>
        {result.ok
          ? "The admin login you typed was used once to make it, and it was not saved."
          : result.message}
      </p>
      {result.findings.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[13px]">
          {result.findings.map((finding) => (
            <li key={finding}>{finding}</li>
          ))}
        </ul>
      )}
    </Notice>
  );
}

function TestResult({ result, onClose }: { result: ConnectionTest; onClose: () => void }) {
  const unsafe = result.status === "unsafe";
  return (
    <Notice
      tone={result.ok ? "info" : unsafe ? "warn" : "error"}
      title={result.ok ? "Connected" : unsafe ? "This login can do more than read" : "Failed"}
      className="mt-4"
      action={
        <Button size="sm" variant="ghost" onClick={onClose}>
          Dismiss
        </Button>
      }
    >
      <p>{result.message}</p>
      {result.findings.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-[13px]">
          {result.findings.map((finding) => (
            <li key={finding}>{finding}</li>
          ))}
        </ul>
      )}
    </Notice>
  );
}

// ── Create and edit ──────────────────────────────────────────────────────────

function ConnectionFormCard({
  connection,
  onDone,
}: {
  connection?: Connection;
  onDone: (result?: ConnectionTest) => void;
}) {
  const editing = connection !== undefined;
  const create = useCreateConnection();
  const update = useUpdateConnection();
  const provision = useProvisionConnection();
  // A new connection can use a login that is already read-only, or have one made with an admin
  // login that is used once and not saved.
  const [mode, setMode] = useState<"existing" | "provision">("existing");
  const [schemas, setSchemas] = useState("");
  const making = !editing && mode === "provision";
  const [form, setForm] = useState<ConnectionForm>(
    connection ? formFromConnection(connection) : emptyForm(),
  );
  const [touched, setTouched] = useState(false);
  const mutation = editing ? update : making ? provision : create;
  const error = mutation.error ? asApiError(mutation.error) : null;

  const problems = problemsIn(form, editing);
  const shown = (field: keyof ConnectionForm) =>
    (touched ? problems[field] : undefined) ?? error?.fieldErrors[field];
  const set = (field: keyof ConnectionForm) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: event.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (Object.keys(problems).length > 0) return;
    if (connection) {
      const body = changesOf(form, connection);
      if (Object.keys(body).length === 0) return onDone();
      update.mutate({ id: connection.id, body }, { onSuccess: () => onDone() });
    } else if (making) {
      provision.mutate(provisionBody(form, schemas), { onSuccess: (result) => onDone(result) });
    } else {
      create.mutate(createBody(form), { onSuccess: () => onDone() });
    }
  }

  return (
    <Card className={cn("overflow-hidden rounded-xl", editing && "bg-surface-2/40")}>
      <CardHeader
        title={editing ? `Edit ${connection.name}` : "Add a connection"}
        description={
          editing
            ? "Changing the host, user, SSL mode or password means the connection has to be tested again."
            : making
              ? "Type an admin login (like postgres) once. It makes a read-only login for this connection and is then forgotten: its password is never saved."
              : "PostgreSQL. The password is stored encrypted and is never shown again."
        }
        aside={
          !editing && (
            <SegmentedControl<"existing" | "provision">
              label="How the login is set up"
              value={mode}
              onChange={setMode}
              options={[
                { value: "existing", label: "I have a read-only login" },
                { value: "provision", label: "Make one for me" },
              ]}
            />
          )
        }
      />
      <form onSubmit={submit} noValidate className="divide-y divide-border">
        <FormSection icon={Server} title="Database">
          {error && !Object.keys(error.fieldErrors).length && (
            <Notice tone="error" title="Could not save the connection">
              {error.message}
            </Notice>
          )}
          <TextField
            label="Name"
            placeholder="Sales warehouse"
            hint="How this connection is called in lists."
            value={form.name}
            onChange={set("name")}
            error={shown("name")}
          />
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_9rem]">
            <TextField
              label="Host"
              placeholder="db.example.com"
              value={form.host}
              onChange={set("host")}
              error={shown("host")}
              autoComplete="off"
            />
            <TextField
              label="Port"
              inputMode="numeric"
              value={form.port}
              onChange={set("port")}
              error={shown("port")}
            />
          </div>
          <TextField
            label="Database"
            placeholder="sales"
            value={form.database}
            onChange={set("database")}
            error={shown("database")}
            autoComplete="off"
          />
        </FormSection>

        <FormSection icon={KeyRound} title={making ? "Admin login (used once)" : "Login"}>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label={making ? "Admin user" : "User"}
              hint={making ? "For example postgres. It is not saved." : undefined}
              value={form.username}
              onChange={set("username")}
              error={shown("username")}
              autoComplete="off"
            />
            <PasswordField
              label={making ? "Admin password" : "Password"}
              value={form.password}
              onChange={set("password")}
              error={shown("password")}
              hint={
                editing
                  ? "Leave empty to keep the saved password."
                  : making
                    ? "Used to make the read-only login, then forgotten. Never saved."
                    : undefined
              }
              autoComplete="new-password"
            />
          </div>
          {making && (
            <TextField
              label="Schemas the new login may read (optional)"
              placeholder="public, finance"
              hint="Leave empty for every schema. It can only read tables, nothing else."
              value={schemas}
              onChange={(event) => setSchemas(event.target.value)}
            />
          )}
        </FormSection>

        <FormSection icon={ShieldCheck} title="Security and privacy">
          <SelectField
            label="Encryption"
            value={form.ssl_mode}
            onChange={set("ssl_mode")}
            options={SSL_OPTIONS}
          />
          <Toggle
            checked={form.share_results_with_ai}
            onChange={(checked) =>
              setForm((current) => ({ ...current, share_results_with_ai: checked }))
            }
            label="Let the AI service see result rows"
            description="Off (recommended): answers and charts are written here from the rows, and nothing from the data is sent to the AI service. On: sample rows go to it to write a nicer explanation."
          />
        </FormSection>

        <div className="flex flex-wrap items-center justify-between gap-3 bg-surface-2/40 px-5 py-3.5">
          <p className="flex items-center gap-1.5 text-[12.5px] text-subtle">
            {!editing && (
              <>
                <ShieldCheck aria-hidden className="size-3.5 shrink-0" />
                After saving, press Test. A connection is used only once a test shows the login is
                read-only.
              </>
            )}
          </p>
          <div className="flex gap-2">
            <Button onClick={() => onDone()}>Cancel</Button>
            <Button type="submit" variant="primary" loading={mutation.isPending}>
              {editing ? (
                "Save changes"
              ) : (
                <>
                  <KeyRound aria-hidden />
                  {making ? "Make the read-only login and connect" : "Save connection"}
                </>
              )}
            </Button>
          </div>
        </div>
      </form>
    </Card>
  );
}

/** One group of fields in the form, with its own small heading. */
function FormSection({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-4 p-5">
      <h4 className="flex items-center gap-2 text-[12px] font-semibold tracking-wide text-subtle uppercase">
        <Icon aria-hidden className="size-3.5" />
        {title}
      </h4>
      {children}
    </section>
  );
}

/** An on/off switch with its name and what it does. */
function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description: string;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border border-border bg-surface-2/40 p-4">
      <div className="min-w-0">
        <p id={`${id}-label`} className="text-[13.5px] font-medium">
          {label}
        </p>
        <p id={`${id}-about`} className="mt-1 text-[12.5px] leading-5 text-muted">
          {description}
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-about`}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-6 w-10 shrink-0 rounded-full border transition-colors duration-150",
          "focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none",
          checked ? "border-accent bg-accent" : "border-border-strong bg-surface-2",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "absolute top-0.5 left-0.5 size-[18px] rounded-full shadow-sm transition-transform duration-150",
            checked ? "translate-x-4 bg-accent-fg" : "bg-muted",
          )}
        />
      </button>
    </div>
  );
}
