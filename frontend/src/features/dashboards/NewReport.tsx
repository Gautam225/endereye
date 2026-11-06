import { CalendarClock, FileSpreadsheet, FileText, Files, ListChecks, X } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { SelectField, TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { plural } from "../../lib/format";
import { AnswersPicker } from "./AnswersPicker";
import { useCreateReport, useKeptItems } from "./queries";
import { RecipientsField } from "./RecipientsField";
import { TimezonePicker } from "./TimezonePicker";
import {
  FORMAT_TEXT,
  WEEKDAYS,
  browserTimezone,
  parseRecipients,
  parseTime,
  scheduleText,
} from "./schedule";
import { currentName } from "./timezones";
import type { Frequency, KeptSummary, ReportFormat, ReportOptions } from "./types";

/** The most kept answers one report can hold (the server's limit). */
const MAX_ANSWERS = 20;
const WEEK = [0, 1, 2, 3, 4, 5, 6];
const WORKWEEK = [0, 1, 2, 3, 4];
const DAYS = Array.from({ length: 28 }, (_, d) => ({ value: String(d + 1), label: String(d + 1) }));

const FORMATS: Array<{ value: ReportFormat; label: string; icon: ReactNode }> = [
  { value: "pdf", label: "PDF", icon: <FileText /> },
  { value: "xlsx", label: "Excel", icon: <FileSpreadsheet /> },
  { value: "both", label: "Both", icon: <Files /> },
];

/**
 * The form for a new report, in three steps that read top to bottom: what is sent, when, and to
 * whom. A line at the bottom says in words what will happen, so nothing has to be guessed.
 */
export function NewReport({
  spaceId,
  options,
  onDone,
}: {
  spaceId: string;
  options: ReportOptions | undefined;
  onDone: () => void;
}) {
  const create = useCreateReport(spaceId);
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<KeptSummary[]>([]);
  const [choosing, setChoosing] = useState(false);
  const kept = useKeptItems(spaceId, "");
  const keptTotal = kept.data?.pages[0]?.total ?? 0;
  const [frequency, setFrequency] = useState<Frequency>("weekly");
  const [time, setTime] = useState("08:00");
  const [weekdays, setWeekdays] = useState<number[]>([0]);
  const [dayOfMonth, setDayOfMonth] = useState(1);
  const [timezone, setTimezone] = useState(browserTimezone());
  const [format, setFormat] = useState<ReportFormat>("pdf");
  const [recipients, setRecipients] = useState("");
  const error = create.error ? asApiError(create.error).message : null;
  const people = parseRecipients(recipients);
  const clock = parseTime(time);
  const [hour, minute] = clock ?? [8, 0];
  const ready = name.trim() !== "" && picked.length > 0 && clock !== null;
  const when = scheduleText({
    frequency,
    hour,
    minute,
    weekdays,
    day_of_month: dayOfMonth,
    timezone: currentName(timezone) || "UTC",
  });

  function toggleDay(day: number) {
    setWeekdays((now) =>
      now.includes(day)
        ? now.length > 1
          ? now.filter((d) => d !== day)
          : now
        : [...now, day].sort(),
    );
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      {
        name: name.trim(),
        item_ids: picked.map((p) => p.id),
        frequency,
        hour,
        minute,
        weekdays,
        day_of_month: dayOfMonth,
        timezone: currentName(timezone.trim()),
        format,
        recipients: people,
        enabled: true,
      },
      { onSuccess: onDone },
    );
  }

  return (
    <Card>
      <CardHeader
        title="New report"
        description="Choose what to send, when, and to whom. It runs as you, so it only holds what you may see."
      />
      <form onSubmit={submit} noValidate>
        <div className="divide-y divide-border">
          <Step
            number={1}
            title="What to send"
            description="Name the report and tick the kept answers it contains."
          >
            <TextField
              label="Report name"
              value={name}
              maxLength={120}
              placeholder="Weekly sales summary"
              onChange={(event) => setName(event.target.value)}
            />

            <div className="space-y-2">
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-[13px] font-medium">Answers to include</p>
                {picked.length > 0 && (
                  <span className="text-[12.5px] text-subtle">
                    {picked.length} of {MAX_ANSWERS}
                  </span>
                )}
              </div>
              {picked.length > 0 && (
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {picked.map((item) => (
                    <li key={item.id} className="flex items-center gap-3 px-3.5 py-2">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13.5px] font-medium">
                          {item.title}
                        </span>
                        {item.title !== item.question && (
                          <span className="block truncate text-[12.5px] text-subtle">
                            {item.question}
                          </span>
                        )}
                      </span>
                      <Button
                        size="icon"
                        variant="ghost"
                        aria-label={`Remove ${item.title}`}
                        onClick={() => setPicked((now) => now.filter((p) => p.id !== item.id))}
                      >
                        <X aria-hidden className="size-3.5" />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              {kept.isPending ? null : keptTotal === 0 ? (
                <p className="rounded-lg border border-dashed border-border px-4 py-5 text-center text-[13px] text-muted">
                  You have not kept any answers yet. Use <b>Keep</b> on an answer in a chat first.
                </p>
              ) : (
                <Button onClick={() => setChoosing(true)}>
                  <ListChecks aria-hidden />
                  {picked.length > 0 ? "Change answers" : "Choose answers"}
                  <span className="text-subtle">· {keptTotal.toLocaleString()} kept</span>
                </Button>
              )}
            </div>
            {choosing && (
              <AnswersPicker
                spaceId={spaceId}
                initial={picked}
                max={MAX_ANSWERS}
                onClose={() => setChoosing(false)}
                onDone={(chosen) => {
                  setPicked(chosen);
                  setChoosing(false);
                }}
              />
            )}

            <SegmentedControl
              label="Send as"
              value={format}
              onChange={setFormat}
              options={FORMATS.map((f) => ({ value: f.value, label: f.label, icon: f.icon }))}
            />
          </Step>

          <Step number={2} title="When" description="How often it goes out, and at what time.">
            <SegmentedControl
              label="Repeats"
              value={frequency}
              onChange={setFrequency}
              options={[
                { value: "daily", label: "Daily" },
                { value: "weekly", label: "Weekly" },
                { value: "monthly", label: "Monthly" },
              ]}
            />

            {frequency === "weekly" && (
              <div role="group" aria-label="Days of the week" className="space-y-1.5">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-[13px] font-medium">On these days</p>
                  <span className="flex gap-3 text-[12.5px]">
                    <button
                      type="button"
                      className="text-accent underline-offset-2 hover:underline"
                      onClick={() => setWeekdays(WORKWEEK)}
                    >
                      Weekdays
                    </button>
                    <button
                      type="button"
                      className="text-accent underline-offset-2 hover:underline"
                      onClick={() => setWeekdays(WEEK)}
                    >
                      Every day
                    </button>
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {WEEKDAYS.map((day, index) => (
                    <button
                      key={day}
                      type="button"
                      aria-pressed={weekdays.includes(index)}
                      aria-label={day}
                      onClick={() => toggleDay(index)}
                      className={cn(
                        "h-9 min-w-12 rounded-lg border px-2.5 text-[13px] font-medium transition-colors",
                        weekdays.includes(index)
                          ? "border-accent/60 bg-accent-soft text-fg"
                          : "border-border text-muted hover:bg-surface-2/60 hover:text-fg",
                      )}
                    >
                      {day.slice(0, 3)}
                    </button>
                  ))}
                </div>
                <p className="text-[12.5px] text-subtle">Choose as many days as you like.</p>
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              {frequency === "monthly" && (
                <SelectField
                  label="On day of the month"
                  value={String(dayOfMonth)}
                  options={DAYS}
                  onChange={(event) => setDayOfMonth(Number(event.target.value))}
                />
              )}
              <TextField
                label="At"
                type="time"
                value={time}
                error={clock ? undefined : "Enter a time, like 08:30."}
                onChange={(event) => setTime(event.target.value)}
              />
            </div>
            <TimezonePicker label="Time zone" value={timezone} onChange={setTimezone} />
          </Step>

          <Step
            number={3}
            title="Who gets it"
            description="Optional. Leave it empty to only make the files."
          >
            <RecipientsField
              id="recipients"
              label="Send to"
              value={recipients}
              onChange={setRecipients}
              help={[
                options && options.allowed_domains.length > 0
                  ? `Allowed domains: ${options.allowed_domains.join(", ")}.`
                  : "",
                options ? `Up to ${plural(options.max_recipients, "address")}.` : "",
              ]
                .filter(Boolean)
                .join(" ")}
            />
          </Step>
        </div>

        {error && (
          <div className="border-t border-border px-6 py-4">
            <Notice tone="error" title="Could not save the report">
              {error}
            </Notice>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-border bg-surface-2/40 px-6 py-4">
          <p className="flex min-w-0 flex-1 items-start gap-2 text-[13px] text-muted">
            <CalendarClock aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
            <span>
              {picked.length > 0 ? plural(picked.length, "answer") : "No answers yet"} as{" "}
              {FORMAT_TEXT[format]}. {when}
              {people.length > 0
                ? `, sent to ${plural(people.length, "person")}.`
                : ", not emailed (files only)."}
            </span>
          </p>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onDone}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={create.isPending} disabled={!ready}>
              Create report
            </Button>
          </div>
        </div>
      </form>
    </Card>
  );
}

/** One step of the form: its title on the left, its fields on the right (stacked on a phone). */
function Step({
  number,
  title,
  description,
  children,
}: {
  number: number;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="grid gap-5 px-6 py-6 lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-10">
      <div className="flex gap-3 lg:block">
        <span
          aria-hidden
          className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent"
        >
          {number}
        </span>
        <div className="lg:mt-2">
          <h3 className="text-[14.5px] font-semibold">{title}</h3>
          <p className="mt-0.5 text-[13px] text-muted">{description}</p>
        </div>
      </div>
      <div className="max-w-2xl min-w-0 space-y-5">{children}</div>
    </section>
  );
}
