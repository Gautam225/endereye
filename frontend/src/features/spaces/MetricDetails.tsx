import { FlaskConical, History, Play, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { BareTextArea, SelectField, TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { ApiError, asApiError } from "../../lib/api";
import { timeAgo } from "../../lib/format";
import {
  testLabel,
  useCreateTest,
  useDeleteTest,
  useExpressionTests,
  useExpressionVersions,
  useRestoreVersion,
  useRunTests,
} from "./metrics";
import { useMembers, useUpdateExpression } from "./queries";
import type { ExpressionChange, SqlExpression } from "./types";

/** True when the server refused a change because a test of the definition fails. */
function testsFailed(error: unknown): error is ApiError {
  return error instanceof ApiError && error.code === "tests_failed";
}

/**
 * What stands behind a shared definition: who owns it, how it changed over time, and the tests
 * that keep it honest. Everyone in the space can read this; editors change it.
 */
export function MetricDetails({
  spaceId,
  item,
  editor,
}: {
  spaceId: string;
  item: SqlExpression;
  editor: boolean;
}) {
  return (
    <div className="mt-2 space-y-5 rounded-lg border border-border bg-surface-2/30 p-4">
      <Ownership spaceId={spaceId} item={item} editor={editor} />
      {editor && <Edit spaceId={spaceId} item={item} />}
      <Tests spaceId={spaceId} item={item} editor={editor} />
      <Versions spaceId={spaceId} item={item} editor={editor} />
    </div>
  );
}

function Ownership({
  spaceId,
  item,
  editor,
}: {
  spaceId: string;
  item: SqlExpression;
  editor: boolean;
}) {
  const members = useMembers(spaceId);
  const update = useUpdateExpression(spaceId);
  const options = (members.data ?? []).filter((m) => m.is_active);

  return (
    <div className="flex flex-wrap items-end gap-4">
      <p className="text-[13px]">
        <span className="text-subtle">Owner </span>
        <b>{item.owner_name ?? "Nobody"}</b>
        <span className="text-subtle"> · version {item.version}</span>
      </p>
      {editor && options.length > 0 && (
        <SelectField
          label="Change owner"
          hideLabel
          className="w-56"
          value={item.owner_id ?? ""}
          options={[
            ...(item.owner_id ? [] : [{ value: "", label: "Choose an owner" }]),
            ...options.map((m) => ({ value: m.user_id, label: m.full_name })),
          ]}
          onChange={(event) =>
            event.target.value &&
            update.mutate({ id: item.id, change: { owner_id: event.target.value } })
          }
        />
      )}
      {update.error && !testsFailed(update.error) && (
        <p role="alert" className="text-[12.5px] text-danger">
          {asApiError(update.error).message}
        </p>
      )}
    </div>
  );
}

function Edit({ spaceId, item }: { spaceId: string; item: SqlExpression }) {
  const update = useUpdateExpression(spaceId);
  const [expression, setExpression] = useState(item.expression);
  const [description, setDescription] = useState(item.description);
  const [note, setNote] = useState("");
  const changed = expression.trim() !== item.expression || description.trim() !== item.description;
  const blocked = testsFailed(update.error) ? update.error : null;

  function save(acceptFailing: boolean) {
    const change: ExpressionChange = {
      expression: expression.trim(),
      description: description.trim(),
      note: note.trim() || undefined,
      accept_failing_tests: acceptFailing,
    };
    update.mutate({ id: item.id, change }, { onSuccess: () => setNote("") });
  }

  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        save(false);
      }}
      className="space-y-3"
    >
      <h4 className="text-[13px] font-semibold">Change the definition</h4>
      <BareTextArea
        aria-label="Expression"
        rows={3}
        className="font-mono text-[12.5px]"
        value={expression}
        onChange={(event) => setExpression(event.target.value)}
      />
      <TextField
        label="Description"
        value={description}
        maxLength={1000}
        onChange={(event) => setDescription(event.target.value)}
      />
      <TextField
        label="Why are you changing it?"
        hint="Kept with the new version, so the next person knows."
        value={note}
        maxLength={300}
        onChange={(event) => setNote(event.target.value)}
      />
      {blocked ? (
        <Notice tone="error" title="Not saved: a test would fail">
          {blocked.message}
          <div className="mt-2">
            <Button size="sm" onClick={() => save(true)} loading={update.isPending}>
              Save anyway
            </Button>
          </div>
        </Notice>
      ) : (
        update.error && (
          <Notice tone="error" title="Not saved">
            {asApiError(update.error).message}
          </Notice>
        )
      )}
      <Button
        type="submit"
        variant="primary"
        size="sm"
        disabled={!changed}
        loading={update.isPending && !blocked}
      >
        Save as a new version
      </Button>
    </form>
  );
}

// ── Tests ────────────────────────────────────────────────────────────────────

function Tests({
  spaceId,
  item,
  editor,
}: {
  spaceId: string;
  item: SqlExpression;
  editor: boolean;
}) {
  const tests = useExpressionTests(spaceId, item.id, true);
  const run = useRunTests(spaceId, item.id);
  const remove = useDeleteTest(spaceId, item.id);
  const create = useCreateTest(spaceId, item.id);
  const [name, setName] = useState("");
  const [where, setWhere] = useState("");
  const [expected, setExpected] = useState("");
  const [tolerance, setTolerance] = useState("0");
  const number = Number(expected);
  const valid = name.trim() !== "" && expected.trim() !== "" && Number.isFinite(number);

  function add(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      {
        name: name.trim(),
        where_sql: where.trim() || null,
        expected: number,
        tolerance: Math.max(0, Number(tolerance) || 0),
      },
      {
        onSuccess: () => {
          setName("");
          setWhere("");
          setExpected("");
        },
      },
    );
  }

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <FlaskConical aria-hidden className="size-3.5 text-accent" />
        <h4 className="text-[13px] font-semibold">Tests</h4>
        {editor && (tests.data?.length ?? 0) > 0 && (
          <Button size="sm" variant="ghost" loading={run.isPending} onClick={() => run.mutate()}>
            <Play aria-hidden className="size-3.5" />
            Run tests
          </Button>
        )}
      </div>
      <p className="text-[12.5px] text-subtle">
        A test says what the definition must give on a table (optionally narrowed by a condition). A
        change that breaks one is refused unless you save it anyway.
      </p>
      {tests.isPending ? (
        <Skeleton className="h-10" />
      ) : tests.isError ? (
        <p className="text-[13px] text-muted">{tests.error.message}</p>
      ) : tests.data.length === 0 ? (
        <p className="text-[13px] text-muted">No tests yet.</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {tests.data.map((test) => (
            <li key={test.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
              <Badge
                tone={
                  test.last_status === "pass"
                    ? "ok"
                    : test.last_status === null
                      ? "neutral"
                      : "error"
                }
              >
                {testLabel(test)}
              </Badge>
              <span className="min-w-0 flex-1 text-[13px]">
                <b className="font-medium">{test.name}</b>{" "}
                <span className="text-subtle">
                  expects {test.expected}
                  {test.tolerance > 0 && ` ± ${test.tolerance}`}
                  {test.where_sql && ` where ${test.where_sql}`}
                </span>
                {test.last_detail && <span className="block text-danger">{test.last_detail}</span>}
              </span>
              {editor && (
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={`Delete test ${test.name}`}
                  loading={remove.isPending && remove.variables === test.id}
                  onClick={() => remove.mutate(test.id)}
                >
                  <Trash2 aria-hidden className="size-3.5" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {(run.error || remove.error) && (
        <p role="alert" className="text-[12.5px] text-danger">
          {asApiError(run.error ?? remove.error).message}
        </p>
      )}
      {editor && item.table_name && (
        <form
          onSubmit={add}
          className="grid gap-3 sm:grid-cols-[1fr_1fr_7rem_6rem_auto] sm:items-end"
        >
          <TextField
            label="Test name"
            value={name}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
          />
          <TextField
            label="Only rows where (optional)"
            value={where}
            placeholder="region = 'North'"
            onChange={(event) => setWhere(event.target.value)}
          />
          <TextField
            label="Expected"
            inputMode="decimal"
            value={expected}
            onChange={(event) => setExpected(event.target.value)}
          />
          <TextField
            label="± Tolerance"
            inputMode="decimal"
            value={tolerance}
            onChange={(event) => setTolerance(event.target.value)}
          />
          <Button type="submit" size="sm" disabled={!valid} loading={create.isPending}>
            Add test
          </Button>
        </form>
      )}
      {editor && !item.table_name && (
        <p className="text-[12.5px] text-subtle">
          Tests need the definition to be written for a table.
        </p>
      )}
      {create.error && (
        <Notice tone="error" title="Test not added">
          {asApiError(create.error).message}
        </Notice>
      )}
    </section>
  );
}

// ── History ──────────────────────────────────────────────────────────────────

function Versions({
  spaceId,
  item,
  editor,
}: {
  spaceId: string;
  item: SqlExpression;
  editor: boolean;
}) {
  const versions = useExpressionVersions(spaceId, item.id, true);
  const restore = useRestoreVersion(spaceId, item.id);
  const blocked = testsFailed(restore.error) ? restore.error : null;

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <History aria-hidden className="size-3.5 text-accent" />
        <h4 className="text-[13px] font-semibold">History</h4>
      </div>
      {versions.isPending ? (
        <Skeleton className="h-10" />
      ) : versions.isError ? (
        <p className="text-[13px] text-muted">{versions.error.message}</p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {versions.data.map((v) => (
            <li key={v.version} className="space-y-1 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2 text-[13px]">
                <Badge tone={v.version === item.version ? "accent" : "neutral"}>v{v.version}</Badge>
                <span className="text-subtle">
                  {timeAgo(v.changed_at)}
                  {v.changed_by_name && ` · ${v.changed_by_name}`}
                </span>
                {v.note && <span className="text-muted">· {v.note}</span>}
                {editor && v.version !== item.version && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto"
                    loading={restore.isPending && restore.variables?.version === v.version}
                    onClick={() => restore.mutate({ version: v.version, acceptFailing: false })}
                  >
                    Restore
                  </Button>
                )}
              </div>
              <pre className="overflow-x-auto rounded-md bg-surface-2/60 px-2.5 py-1.5 font-mono text-[12px] whitespace-pre-wrap">
                {v.expression}
              </pre>
            </li>
          ))}
        </ul>
      )}
      {blocked && restore.variables && (
        <Notice tone="error" title="Not restored: a test would fail">
          {blocked.message}
          <div className="mt-2">
            <Button
              size="sm"
              onClick={() =>
                restore.mutate({ version: restore.variables!.version, acceptFailing: true })
              }
            >
              Restore anyway
            </Button>
          </div>
        </Notice>
      )}
      {restore.error && !blocked && (
        <p role="alert" className="text-[12.5px] text-danger">
          {asApiError(restore.error).message}
        </p>
      )}
    </section>
  );
}
