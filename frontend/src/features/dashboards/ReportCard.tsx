import {
  CalendarClock,
  ChevronDown,
  Download,
  FileSpreadsheet,
  FileText,
  Play,
  Trash2,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { plural, timeAgo } from "../../lib/format";
import {
  useDeleteReport,
  useDownloadReportFile,
  useReportRuns,
  useRunReport,
  useUpdateReport,
} from "./queries";
import { useDeepLink } from "./deepLink";
import { FORMAT_TEXT, RUN_TEXT, scheduleText } from "./schedule";
import type { Report, ReportRun } from "./types";

const RUN_TONE: Record<ReportRun["status"], "ok" | "error" | "neutral"> = {
  ok: "ok",
  failed: "error",
  running: "neutral",
};

/** One report: what it holds, who gets it, when it runs next, and how the last run went. */
export function ReportCard({ spaceId, report }: { spaceId: string; report: Report }) {
  const run = useRunReport(spaceId);
  const update = useUpdateReport(spaceId);
  const remove = useDeleteReport(spaceId);
  const [cardRef, targeted] = useDeepLink("report", report.id);
  const [open, setOpen] = useState(targeted);
  const [confirming, setConfirming] = useState(false);
  const last = report.last_run;
  const running = last?.status === "running";
  const titles = report.items.map((item) => item.title);
  const error = run.error ?? update.error ?? remove.error;

  return (
    <div ref={cardRef} className={targeted ? "deep-link-glow" : undefined}>
      <Card className={cn(!report.enabled && "opacity-90")}>
        <div className="flex flex-wrap items-start gap-4 px-5 py-4">
          <span
            aria-hidden
            className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent"
          >
            <CalendarClock className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="flex flex-wrap items-center gap-2 text-[15px] font-semibold">
              <span className="truncate">{report.name}</span>
              {!report.enabled && <Badge tone="neutral">Paused</Badge>}
            </h3>
            <p className="mt-0.5 text-[13px] text-muted">
              {scheduleText(report)} · {FORMAT_TEXT[report.format]}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              loading={run.isPending || running}
              onClick={() => run.mutate(report.id, { onSuccess: () => setOpen(true) })}
              title="Make it now and send it to the recipients"
            >
              <Play aria-hidden className="size-3.5" />
              Run now
            </Button>
            <Button
              size="sm"
              variant="ghost"
              loading={update.isPending}
              onClick={() =>
                update.mutate({ id: report.id, changes: { enabled: !report.enabled } })
              }
            >
              {report.enabled ? "Pause" : "Resume"}
            </Button>
            {confirming ? (
              <span className="flex items-center gap-1">
                <span className="text-[13px] text-muted">Delete?</span>
                <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                  Keep
                </Button>
                <Button
                  size="sm"
                  className="text-danger hover:bg-danger-soft"
                  loading={remove.isPending}
                  onClick={() => remove.mutate(report.id)}
                >
                  Delete
                </Button>
              </span>
            ) : (
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Delete ${report.name}`}
                title="Delete this report"
                onClick={() => setConfirming(true)}
              >
                <Trash2 aria-hidden className="size-4" />
              </Button>
            )}
          </div>
        </div>

        {error && (
          <div className="px-5 pb-4">
            <Notice tone="error" title="That didn't work">
              {asApiError(error).message}
            </Notice>
          </div>
        )}

        <dl className="grid gap-px border-y border-border bg-border md:grid-cols-3">
          <Info label="Contains">
            <ul className="flex flex-wrap gap-1.5">
              {titles.map((title, index) => (
                <li
                  key={`${title}-${index}`}
                  className="max-w-full truncate rounded-md bg-surface-2 px-2 py-0.5 text-[12.5px]"
                >
                  {title}
                </li>
              ))}
            </ul>
          </Info>
          <Info label="Sent to">
            {report.recipients.length > 0 ? (
              <ul className="flex flex-wrap gap-1.5">
                {report.recipients.map((email) => (
                  <li
                    key={email}
                    className="max-w-full truncate rounded-md bg-surface-2 px-2 py-0.5 text-[12.5px]"
                  >
                    {email}
                  </li>
                ))}
              </ul>
            ) : (
              <span className="text-muted">Nobody. The files are only kept here.</span>
            )}
          </Info>
          <Info label="Runs">
            <div className="space-y-2">
              <p>
                <span className="text-subtle">Next: </span>
                {report.next_run_at && report.enabled
                  ? new Date(report.next_run_at).toLocaleString(undefined, {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })
                  : "not scheduled"}
              </p>
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-subtle">Last: </span>
                {last ? (
                  <>
                    <Badge tone={RUN_TONE[last.status]}>{RUN_TEXT[last.status]}</Badge>
                    <span>{timeAgo(last.started_at)}</span>
                  </>
                ) : (
                  "never run"
                )}
              </p>
              {last?.error && <p className="text-[12.5px] text-muted">{last.error}</p>}
            </div>
          </Info>
        </dl>

        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((now) => !now)}
          className="flex w-full items-center gap-2 px-5 py-3 text-left text-[13px] font-medium text-muted transition-colors hover:bg-surface-2/50 hover:text-fg"
        >
          <ChevronDown
            aria-hidden
            className={cn("size-4 transition-transform", open && "rotate-180")}
          />
          History and files
        </button>
        {open && (
          <div className="border-t border-border px-5 py-4">
            <Runs spaceId={spaceId} reportId={report.id} />
          </div>
        )}
      </Card>
    </div>
  );
}

function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 bg-surface px-5 py-4 text-[13.5px]">
      <dt className="mb-2 text-[11.5px] font-semibold tracking-wide text-subtle uppercase">
        {label}
      </dt>
      <dd>{children}</dd>
    </div>
  );
}

function Runs({ spaceId, reportId }: { spaceId: string; reportId: string }) {
  const runs = useReportRuns(spaceId, reportId);
  const download = useDownloadReportFile(spaceId);

  if (runs.isPending) return <Skeleton className="h-16" />;
  if (runs.isError) return <p className="text-[13px] text-muted">{runs.error.message}</p>;
  if (runs.data.length === 0) return <p className="text-[13px] text-muted">No runs yet.</p>;
  return (
    <ul className="divide-y divide-border rounded-lg border border-border text-[13px]">
      {runs.data.map((run) => (
        <li key={run.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
          <span className="w-28 shrink-0 text-subtle">{timeAgo(run.started_at)}</span>
          <Badge tone={RUN_TONE[run.status]}>{RUN_TEXT[run.status]}</Badge>
          <span className="text-subtle">
            {run.trigger === "manual" ? "run by hand" : "on schedule"}
            {run.emailed_to.length > 0 && ` · sent to ${plural(run.emailed_to.length, "person")}`}
          </span>
          {run.error && (
            <span className="min-w-0 basis-full text-muted sm:basis-auto">{run.error}</span>
          )}
          <span className="ml-auto flex gap-1.5">
            {run.files.map((name) => (
              <Button
                key={name}
                size="sm"
                loading={download.isPending && download.variables?.name === name}
                onClick={() => download.mutate({ reportId, runId: run.id, name })}
              >
                {name.endsWith(".pdf") ? (
                  <FileText aria-hidden className="size-3.5" />
                ) : (
                  <FileSpreadsheet aria-hidden className="size-3.5" />
                )}
                {name.endsWith(".pdf") ? "PDF" : "Excel"}
                <Download aria-hidden className="size-3.5" />
              </Button>
            ))}
          </span>
        </li>
      ))}
      {download.error && (
        <li className="px-4 py-2.5 text-danger">{asApiError(download.error).message}</li>
      )}
    </ul>
  );
}
