import {
  Activity,
  ChevronLeft,
  ChevronRight,
  Flag,
  MessageSquare,
  Search,
  ThumbsDown,
  ThumbsUp,
  Timer,
  TriangleAlert,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PageHeader } from "../../components/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { SelectField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { Skeleton } from "../../components/ui/Skeleton";
import { StatTile } from "../../components/ui/StatTile";
import { Badge } from "../../components/ui/Status";
import { cn } from "../../lib/cn";
import { count, milliseconds, timeAgo } from "../../lib/format";
import { useSpaces } from "../spaces/queries";
import { ReviewPanel } from "./ReviewPanel";
import { STATUS_LABEL, STATUS_TONE } from "./status";
import { PAGE_SIZE, useMessages, useSummary } from "./queries";
import type { Filters, Row, Summary } from "./types";

const DAYS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
];

/** "2026-10-26" -> "Oct 26" */
const shortDay = (day: string) =>
  new Date(`${day}T00:00:00`).toLocaleDateString("en", { month: "short", day: "numeric" });
const STATUSES = [
  { value: "", label: "Any status" },
  { value: "ok", label: "Answered with data" },
  { value: "empty", label: "No rows" },
  { value: "answer", label: "Answered from documents" },
  { value: "clarify", label: "Asked back" },
  { value: "declined", label: "Declined" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Stopped" },
];
const FEEDBACK = [
  { value: "", label: "Any feedback" },
  { value: "down", label: "Thumbs down" },
  { value: "up", label: "Thumbs up" },
  { value: "none", label: "No feedback" },
];
const REVIEW = [
  { value: "", label: "Any review state" },
  { value: "needs_review", label: "Needs review" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed" },
];

const START: Filters = {
  days: 30,
  status: "",
  feedback: "",
  review: "",
  spaceId: "",
  text: "",
  offset: 0,
};

/** How the assistant is doing across all spaces, and a queue of answers that need a look. */
export function MonitoringPage() {
  const [filters, setFilters] = useState<Filters>(START);
  const [text, setText] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const spaces = useSpaces();
  const summary = useSummary(filters);
  const messages = useMessages(filters);

  // Typing in the search box waits a moment, so each keystroke does not reload the list.
  useEffect(() => {
    const timer = setTimeout(
      () => setFilters((current) => ({ ...current, text: text.trim(), offset: 0 })),
      300,
    );
    return () => clearTimeout(timer);
  }, [text]);

  const change = (part: Partial<Filters>) =>
    setFilters((current) => ({ ...current, offset: 0, ...part }));
  const total = messages.data?.total ?? 0;
  const filtered = Boolean(
    filters.status || filters.feedback || filters.review || filters.spaceId || filters.text,
  );

  return (
    <>
      <PageHeader
        title="Monitoring"
        description="How questions are being answered across all spaces: volume, failures, speed and feedback. Result data is never shown here."
        actions={
          <SegmentedControl
            label="Period"
            value={String(filters.days)}
            onChange={(value) => change({ days: Number(value) })}
            options={DAYS}
          />
        }
      />

      <div className="mb-6 flex flex-wrap items-center gap-2">
        <label className="relative block min-w-60 flex-1">
          <span className="sr-only">Search questions</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle"
          />
          <input
            type="search"
            placeholder="Search questions, for example revenue"
            maxLength={200}
            value={text}
            onChange={(event) => setText(event.target.value)}
            className="h-9 w-full rounded-lg border border-border bg-surface pr-3 pl-9 text-[14px] shadow-card placeholder:text-subtle hover:border-border-strong focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25 focus-visible:outline-none"
          />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <div className="w-40">
            <SelectField
              hideLabel
              label="Space"
              value={filters.spaceId}
              options={[
                { value: "", label: "All spaces" },
                ...(spaces.data ?? []).map((s) => ({ value: s.id, label: s.name })),
              ]}
              onChange={(event) => change({ spaceId: event.target.value })}
            />
          </div>
          <div className="w-52">
            <SelectField
              hideLabel
              label="Status"
              value={filters.status}
              options={STATUSES}
              onChange={(event) => change({ status: event.target.value })}
            />
          </div>
          <div className="w-44">
            <SelectField
              hideLabel
              label="Feedback"
              value={filters.feedback}
              options={FEEDBACK}
              onChange={(event) => change({ feedback: event.target.value })}
            />
          </div>
          <div className="w-48">
            <SelectField
              hideLabel
              label="Review"
              value={filters.review}
              options={REVIEW}
              onChange={(event) => change({ review: event.target.value })}
            />
          </div>
          {filtered && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setText("");
                setFilters({ ...START, days: filters.days });
              }}
            >
              <X aria-hidden />
              Clear filters
            </Button>
          )}
        </div>
      </div>

      <SummaryBlock
        summary={summary.data}
        loading={summary.isPending}
        error={summary.error?.message}
      />

      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card className="overflow-hidden rounded-xl">
          <CardHeader
            title="Questions"
            description={messages.data ? `${count(total)} in this view` : undefined}
          />
          {messages.isPending ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : messages.isError ? (
            <div className="p-4">
              <Notice tone="error" title="Could not load the questions">
                {messages.error.message}
              </Notice>
            </div>
          ) : messages.data.items.length === 0 ? (
            <EmptyState icon={Activity} title="Nothing matches these filters">
              Try a longer period or clear a filter.
            </EmptyState>
          ) : (
            <>
              <ul className="divide-y divide-border">
                {messages.data.items.map((row) => (
                  <MessageRow
                    key={row.id}
                    row={row}
                    active={row.id === selected}
                    onSelect={() => setSelected(row.id)}
                  />
                ))}
              </ul>
              <div className="flex items-center justify-between border-t border-border bg-surface-2/30 px-5 py-2.5 text-[13px] text-muted">
                <span>
                  {count(filters.offset + 1)}-{count(Math.min(filters.offset + PAGE_SIZE, total))}{" "}
                  of {count(total)}
                </span>
                <span className="flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={filters.offset === 0}
                    onClick={() =>
                      setFilters((c) => ({ ...c, offset: Math.max(0, c.offset - PAGE_SIZE) }))
                    }
                  >
                    <ChevronLeft aria-hidden className="size-4" />
                    Newer
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={filters.offset + PAGE_SIZE >= total}
                    onClick={() => setFilters((c) => ({ ...c, offset: c.offset + PAGE_SIZE }))}
                  >
                    Older
                    <ChevronRight aria-hidden className="size-4" />
                  </Button>
                </span>
              </div>
            </>
          )}
        </Card>

        <div className="lg:sticky lg:top-6">
          <ReviewPanel id={selected} onClose={() => setSelected(null)} />
        </div>
      </div>
    </>
  );
}

function SummaryBlock({
  summary,
  loading,
  error,
}: {
  summary: Summary | undefined;
  loading: boolean;
  error?: string;
}) {
  if (error) {
    return (
      <Notice tone="error" title="Could not load the summary">
        {error}
      </Notice>
    );
  }
  if (loading || !summary) return <Skeleton className="h-28 rounded-xl" />;
  const failed = summary.by_status.failed ?? 0;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Questions" icon={MessageSquare} value={count(summary.questions)} />
        <StatTile
          label="Failed"
          icon={TriangleAlert}
          tone={summary.failure_rate > 0.1 ? "danger" : "default"}
          value={`${(summary.failure_rate * 100).toFixed(1)}%`}
          hint={`${count(failed)} of the answers that finished`}
        />
        <StatTile
          label="Typical speed"
          icon={Timer}
          value={summary.avg_total_ms === null ? "-" : milliseconds(summary.avg_total_ms)}
          hint={
            summary.p95_total_ms === null
              ? undefined
              : `Slowest 5%: ${milliseconds(summary.p95_total_ms)}`
          }
        />
        <StatTile
          label="Needs review"
          icon={Flag}
          tone={summary.needs_review > 0 ? "warn" : "default"}
          value={count(summary.needs_review)}
          hint={`${count(summary.thumbs_up)} thumbs up · ${count(summary.thumbs_down)} down`}
        />
      </div>
      {summary.by_day.length > 1 && (
        <Card className="rounded-xl">
          <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
            <div>
              <p className="text-[15px] font-semibold">Questions per day</p>
              <p className="text-[12.5px] text-subtle">Volume and failures over the period</p>
            </div>
            <div className="flex items-center gap-4 text-[12.5px] text-muted">
              <LegendKey color="var(--chart-1)">Questions</LegendKey>
              <LegendKey color="var(--danger)">Failed</LegendKey>
            </div>
          </div>
          <div className="px-3 pt-3 pb-3" role="img" aria-label="Questions and failures per day">
            <ResponsiveContainer width="100%" height={170}>
              <BarChart data={summary.by_day} barGap={4} margin={{ top: 4, right: 8 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="day"
                  tickFormatter={shortDay}
                  tick={{ fill: "var(--text-subtle)", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={24}
                />
                <YAxis
                  width={32}
                  allowDecimals={false}
                  tick={{ fill: "var(--text-subtle)", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  labelFormatter={(label) => shortDay(String(label))}
                  contentStyle={{
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    fontSize: 13,
                  }}
                  cursor={{ fill: "var(--surface-2)", opacity: 0.6 }}
                />
                <Bar
                  dataKey="questions"
                  name="Questions"
                  fill="var(--chart-1)"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={32}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="failed"
                  name="Failed"
                  fill="var(--danger)"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={32}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}
    </div>
  );
}

function LegendKey({ color, children }: { color: string; children: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className="size-2.5 rounded-sm" style={{ background: color }} />
      {children}
    </span>
  );
}

function MessageRow({
  row,
  active,
  onSelect,
}: {
  row: Row;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        aria-current={active ? "true" : undefined}
        onClick={onSelect}
        className={cn(
          "block w-full border-l-2 px-5 py-3.5 text-left transition-colors focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none focus-visible:ring-inset",
          active ? "border-accent bg-accent-soft/40" : "border-transparent hover:bg-surface-2/60",
        )}
      >
        <span className="flex items-baseline justify-between gap-3">
          <span className="truncate text-[14px] font-medium">{row.question}</span>
          <span className="shrink-0 text-[12px] text-subtle">{timeAgo(row.created_at)}</span>
        </span>
        <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
          <Badge tone={STATUS_TONE[row.status]}>{STATUS_LABEL[row.status]}</Badge>
          {row.feedback === "down" && (
            <Badge tone="warn">
              <ThumbsDown aria-hidden className="mr-1 size-3" />
              Down
            </Badge>
          )}
          {row.feedback === "up" && (
            <Badge tone="ok">
              <ThumbsUp aria-hidden className="mr-1 size-3" />
              Up
            </Badge>
          )}
          {row.review_status && <Badge>{row.review_status}</Badge>}
          <span className="min-w-0 truncate text-[12.5px] text-subtle">
            {row.space_name} · {row.user_name}
            {row.total_ms !== null && ` · ${milliseconds(row.total_ms)}`}
            {row.attempts > 1 && ` · ${row.attempts} tries`}
          </span>
        </span>
      </button>
    </li>
  );
}
