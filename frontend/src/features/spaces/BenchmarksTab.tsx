import { ChevronRight, Gauge, Play, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { BareTextArea, TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { AccuracyCard } from "./AccuracyCard";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { milliseconds, plural, timeAgo } from "../../lib/format";
import {
  OUTCOME_LABEL,
  OUTCOME_TONE,
  RUN_STATUS_TEXT,
  accuracyText,
  isActive,
  progressOf,
  scoreText,
} from "./benchmarks";
import {
  useBenchmarkRun,
  useBenchmarkRuns,
  useBenchmarks,
  useCreateBenchmark,
  useDeleteBenchmark,
  useStartBenchmarkRun,
} from "./queries";
import type { BenchmarkItem, BenchmarkResult, BenchmarkRun, Space } from "./types";

/**
 * Benchmarks: questions with SQL that is known to answer them. A run lets the assistant answer
 * each question on its own and compares what its query *returns* with what the reference
 * returns, because a query can run without errors and still give the wrong answer.
 */
export function BenchmarksTab({ space }: { space: Space }) {
  const items = useBenchmarks(space.id);
  const runs = useBenchmarkRuns(space.id);
  const [chosen, setChosen] = useState<string | null>(null);
  const latest = runs.data?.[0];
  const selected = chosen ?? latest?.id ?? null;

  return (
    <div className="space-y-5">
      <RunCard
        spaceId={space.id}
        questions={items.data?.length ?? 0}
        runs={runs.data ?? []}
        loading={runs.isPending}
        selected={selected}
        onSelect={setChosen}
      />
      <AccuracyCard spaceId={space.id} latestStatus={latest?.status} selectedRunId={selected} />
      {selected && <RunResults spaceId={space.id} runId={selected} />}
      <QuestionsCard spaceId={space.id} items={items.data} error={items.error?.message} />
    </div>
  );
}

// ── Running ──────────────────────────────────────────────────────────────────

function RunCard({
  spaceId,
  questions,
  runs,
  loading,
  selected,
  onSelect,
}: {
  spaceId: string;
  questions: number;
  runs: BenchmarkRun[];
  loading: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const start = useStartBenchmarkRun(spaceId);
  const error = start.error ? asApiError(start.error) : null;
  const active = isActive(runs[0]);

  return (
    <Card>
      <CardHeader
        title={
          <>
            <Gauge aria-hidden className="size-4 text-accent" />
            Score the assistant
          </>
        }
        description="The assistant answers every question itself, then its result is compared with the reference result. Each question costs one or more AI calls."
        aside={
          <Button
            variant="primary"
            disabled={questions === 0 || active}
            loading={start.isPending}
            onClick={() => start.mutate(undefined, { onSuccess: (run) => onSelect(run.id) })}
          >
            <Play aria-hidden />
            {active ? "Running…" : `Run ${plural(questions, "question")}`}
          </Button>
        }
      />
      {error && (
        <div className="p-5 pb-0">
          <Notice tone="error" title="Could not start the run">
            {error.message}
          </Notice>
        </div>
      )}
      {loading ? (
        <Skeleton className="m-5 h-16" />
      ) : runs.length === 0 ? (
        <p className="p-5 text-[13px] text-muted">
          {questions === 0 ? "Add a question below first." : "No runs yet."}
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {runs.map((run) => (
            <li key={run.id}>
              <button
                type="button"
                onClick={() => onSelect(run.id)}
                aria-current={run.id === selected}
                className={cn(
                  "flex w-full items-center gap-4 px-5 py-3 text-left transition-colors hover:bg-surface-2/60",
                  run.id === selected && "bg-surface-2/60",
                )}
              >
                <span className="w-14 shrink-0 text-[17px] font-semibold tabular-nums">
                  {accuracyText(run.accuracy)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13.5px]">
                    {scoreText(run)}
                    {run.status !== "finished" && ` · ${RUN_STATUS_TEXT[run.status]}`}
                  </span>
                  <span className="block text-[12.5px] text-subtle">
                    {timeAgo(run.started_at)}
                    {run.started_by_name && ` · by ${run.started_by_name}`}
                  </span>
                </span>
                {run.status === "running" && (
                  <span className="w-24 shrink-0">
                    <Progress value={progressOf(run)} />
                  </span>
                )}
                <ChevronRight aria-hidden className="size-4 shrink-0 text-subtle" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Progress({ value }: { value: number }) {
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value * 100)}
      className="h-1.5 overflow-hidden rounded-full bg-border"
    >
      <div
        className="h-full rounded-full bg-accent transition-[width] duration-500"
        style={{ width: `${Math.round(value * 100)}%` }}
      />
    </div>
  );
}

// ── The results of one run ───────────────────────────────────────────────────

function RunResults({ spaceId, runId }: { spaceId: string; runId: string }) {
  const run = useBenchmarkRun(spaceId, runId);

  if (run.isPending) return <Skeleton className="h-40" />;
  if (run.isError) {
    return (
      <Notice tone="error" title="Could not load this run">
        {run.error.message}
      </Notice>
    );
  }
  const data = run.data;

  return (
    <Card>
      <CardHeader
        title={`Results · ${accuracyText(data.accuracy)}`}
        description={
          data.status === "running"
            ? `${data.done} of ${data.total} questions answered so far…`
            : `${scoreText(data)}. ${RUN_STATUS_TEXT[data.status]}.`
        }
        aside={
          <div className="flex flex-wrap gap-1.5">
            <Badge tone="ok">{data.correct} correct</Badge>
            {data.incorrect > 0 && <Badge tone="error">{data.incorrect} wrong</Badge>}
            {data.failed > 0 && <Badge tone="error">{data.failed} no query</Badge>}
            {data.reference_errors > 0 && (
              <Badge tone="neutral">{data.reference_errors} set aside</Badge>
            )}
          </div>
        }
      />
      {data.error && (
        <div className="p-5 pb-0">
          <Notice tone="warn" title="This run stopped early">
            {data.error}
          </Notice>
        </div>
      )}
      {data.results.length === 0 ? (
        <p className="p-5 text-[13px] text-muted">No question has been answered yet.</p>
      ) : (
        <ul className="divide-y divide-border">
          {data.results.map((result) => (
            <ResultRow key={result.id} result={result} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function ResultRow({ result }: { result: BenchmarkResult }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="px-5 py-3">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <Badge tone={OUTCOME_TONE[result.outcome]}>{OUTCOME_LABEL[result.outcome]}</Badge>
        <div className="min-w-0 flex-1">
          <p className="text-[14px]">{result.question}</p>
          {result.detail && <p className="text-[12.5px] text-muted">{result.detail}</p>}
          <p className="text-[12.5px] text-subtle">
            {result.attempts > 0 && `${plural(result.attempts, "attempt")} · `}
            {result.expected_rows !== null && `reference ${plural(result.expected_rows, "row")}`}
            {result.actual_rows !== null && ` · answer ${plural(result.actual_rows, "row")}`}
            {result.duration_ms > 0 && ` · ${milliseconds(result.duration_ms)}`}
          </p>
        </div>
        <Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen(!open)}>
          SQL
          <ChevronRight
            aria-hidden
            className={cn("transition-transform duration-200", open && "rotate-90")}
          />
        </Button>
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          <Sql label="Reference" sql={result.expected_sql} />
          {result.generated_sql ? (
            <Sql label="The assistant wrote" sql={result.generated_sql} />
          ) : (
            <p className="text-[12.5px] text-subtle">The assistant did not write a query.</p>
          )}
        </div>
      )}
    </li>
  );
}

function Sql({ label, sql }: { label: string; sql: string }) {
  return (
    <div>
      <p className="mb-1 text-[11px] font-semibold tracking-wide text-subtle uppercase">{label}</p>
      <pre className="overflow-x-auto rounded-md bg-surface-2 p-3 font-mono text-[12.5px] leading-5">
        {sql}
      </pre>
    </div>
  );
}

// ── The questions ────────────────────────────────────────────────────────────

function QuestionsCard({
  spaceId,
  items,
  error,
}: {
  spaceId: string;
  items: BenchmarkItem[] | undefined;
  error: string | undefined;
}) {
  const [adding, setAdding] = useState(false);
  return (
    <Card>
      <CardHeader
        title="Benchmark questions"
        description="A question and the SQL that is known to answer it correctly. The SQL is checked and run when you save it."
        aside={
          !adding && (
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus aria-hidden />
              Add question
            </Button>
          )
        }
      />
      {adding && <AddQuestion spaceId={spaceId} onDone={() => setAdding(false)} />}
      {error ? (
        <div className="p-5">
          <Notice tone="error" title="Could not load the questions">
            {error}
          </Notice>
        </div>
      ) : items === undefined ? (
        <Skeleton className="m-5 h-16" />
      ) : items.length === 0 ? (
        !adding && (
          <EmptyState icon={Gauge} title="No benchmark questions yet">
            Add questions whose right answer you know, such as &quot;How many customers do we
            have?&quot; with the SQL that counts them.
          </EmptyState>
        )
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <QuestionRow key={item.id} spaceId={spaceId} item={item} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function QuestionRow({ spaceId, item }: { spaceId: string; item: BenchmarkItem }) {
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteBenchmark(spaceId);
  return (
    <li className="px-5 py-3">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-[14px]">
            {item.question}
            {item.ordered && <Badge>Row order matters</Badge>}
            {item.last_outcome && (
              <Badge tone={OUTCOME_TONE[item.last_outcome]}>
                Last run: {OUTCOME_LABEL[item.last_outcome]}
              </Badge>
            )}
          </p>
          <pre className="mt-1.5 overflow-x-auto rounded-md bg-surface-2 p-2.5 font-mono text-[12.5px] leading-5 text-muted">
            {item.expected_sql}
          </pre>
          {remove.error && (
            <p role="alert" className="mt-1 text-[12.5px] text-danger">
              {asApiError(remove.error).message}
            </p>
          )}
        </div>
        {confirming ? (
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
              Keep
            </Button>
            <Button
              size="sm"
              variant="primary"
              className="bg-danger hover:bg-danger/90"
              loading={remove.isPending}
              onClick={() => remove.mutate(item.id, { onSettled: () => setConfirming(false) })}
            >
              Delete
            </Button>
          </div>
        ) : (
          <Button
            size="icon"
            variant="ghost"
            aria-label="Delete this question"
            onClick={() => setConfirming(true)}
          >
            <Trash2 aria-hidden />
          </Button>
        )}
      </div>
    </li>
  );
}

function AddQuestion({ spaceId, onDone }: { spaceId: string; onDone: () => void }) {
  const create = useCreateBenchmark(spaceId);
  const [question, setQuestion] = useState("");
  const [sql, setSql] = useState("");
  const [ordered, setOrdered] = useState(false);
  const [touched, setTouched] = useState(false);
  const error = create.error ? asApiError(create.error) : null;
  const questionProblem = question.trim().length < 3 ? "Write the question." : undefined;
  const sqlProblem = sql.trim() ? undefined : "Write the SQL that answers it.";

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (questionProblem || sqlProblem) return;
    create.mutate(
      { question: question.trim(), expected_sql: sql.trim(), ordered },
      { onSuccess: onDone },
    );
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4 border-b border-border p-5">
      {error && (
        <Notice tone="error" title="Could not save the question">
          {error.message}
        </Notice>
      )}
      <TextField
        label="Question"
        placeholder="What is the revenue by customer?"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        error={touched ? questionProblem : undefined}
      />
      <div className="space-y-1.5">
        <label htmlFor="benchmark-sql" className="block text-[13px] font-medium">
          SQL that answers it correctly
        </label>
        <BareTextArea
          id="benchmark-sql"
          rows={5}
          spellCheck={false}
          className="font-mono text-[13px]"
          placeholder="SELECT customer, sum(amount) AS revenue FROM orders GROUP BY customer"
          value={sql}
          onChange={(event) => setSql(event.target.value)}
          aria-invalid={touched && sqlProblem ? true : undefined}
        />
        {touched && sqlProblem && <p className="text-[12.5px] text-danger">{sqlProblem}</p>}
      </div>
      <label className="flex items-start gap-2.5 text-[13px]">
        <input
          type="checkbox"
          checked={ordered}
          onChange={(event) => setOrdered(event.target.checked)}
          className="mt-0.5 size-3.5 accent-[var(--color-accent)]"
        />
        <span>
          <span className="font-medium">Row order matters</span>
          <span className="block text-muted">
            Tick for rankings. Otherwise the same rows in any order count as right.
          </span>
        </span>
      </label>
      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" loading={create.isPending}>
          Check and save
        </Button>
      </div>
    </form>
  );
}
