import { Bell, ChevronDown, Play, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { SelectField, TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { timeAgo } from "../../lib/format";
import { useExpressions } from "../spaces/queries";
import { useDeepLink } from "./deepLink";
import { EmailNotice } from "./EmailNotice";
import { RecipientsField } from "./RecipientsField";
import { SpaceTabs } from "./SpaceTabs";
import {
  INTERVALS,
  OPERATOR_WORDS,
  RENOTIFY,
  STATE_TEXT,
  STATE_TONE,
  conditionText,
  everyText,
  useAlertEvents,
  useAlerts,
  useCheckAlert,
  useCreateAlert,
  useDeleteAlert,
  useUpdateAlert,
  valueText,
  type Alert,
  type AlertSource,
  type Operator,
} from "./alerts";
import { useDashboards, useReportOptions } from "./queries";
import { parseRecipients } from "./schedule";

/**
 * Alerts: "tell me when this number crosses that line". Each one watches a shared metric or the
 * first number of an answer you kept, and is checked on a schedule as you.
 */
export function AlertsPage() {
  const { spaceId = "" } = useParams();
  const alerts = useAlerts(spaceId);
  const options = useReportOptions(spaceId);
  const [creating, setCreating] = useState(false);

  return (
    <SpaceTabs
      spaceId={spaceId}
      section="alerts"
      title="Alerts"
      description="Get told when a number crosses a line, such as the share of failed orders going above 3%. You are told when it starts, not at every check, and again when it is back to normal."
      actions={
        <Button variant="primary" onClick={() => setCreating(true)} disabled={creating}>
          <Plus aria-hidden />
          New alert
        </Button>
      }
    >
      <div className="space-y-5">
        {options.data && !options.data.email_configured && (
          <EmailNotice>Alerts are still checked and shown here, but nobody is emailed.</EmailNotice>
        )}
        {creating && <NewAlert spaceId={spaceId} onDone={() => setCreating(false)} />}
        {alerts.isPending ? (
          <Skeleton className="h-32" />
        ) : alerts.isError ? (
          <Notice tone="error" title="Could not load your alerts">
            {alerts.error.message}
          </Notice>
        ) : alerts.data.length === 0 && !creating ? (
          <Card>
            <EmptyState icon={Bell} title="No alerts yet">
              Choose <b>New alert</b> to watch a metric. Shared metrics are defined in the space
              under{" "}
              <Link to={`/spaces/${spaceId}`} className="text-accent hover:underline">
                Knowledge
              </Link>
              .
            </EmptyState>
          </Card>
        ) : (
          alerts.data.map((alert) => <AlertCard key={alert.id} spaceId={spaceId} alert={alert} />)
        )}
      </div>
    </SpaceTabs>
  );
}

// ── Making one ───────────────────────────────────────────────────────────────

function NewAlert({ spaceId, onDone }: { spaceId: string; onDone: () => void }) {
  const create = useCreateAlert(spaceId);
  const metrics = useExpressions(spaceId);
  const dashboards = useDashboards(spaceId);
  const kept = (dashboards.data ?? []).flatMap((d) => d.items);
  const watchable = (metrics.data ?? []).filter((m) => m.table_name !== null);

  const [name, setName] = useState("");
  const [source, setSource] = useState<AlertSource>("metric");
  const [metricId, setMetricId] = useState("");
  const [itemId, setItemId] = useState("");
  const [where, setWhere] = useState("");
  const [column, setColumn] = useState("");
  const [operator, setOperator] = useState<Operator>("gt");
  const [threshold, setThreshold] = useState("");
  const [interval, setIntervalMinutes] = useState(60);
  const [renotify, setRenotify] = useState(24);
  const [recovery, setRecovery] = useState(true);
  const [recipients, setRecipients] = useState("");
  const error = create.error ? asApiError(create.error).message : null;
  const number = Number(threshold);
  const valid =
    name.trim() !== "" &&
    threshold.trim() !== "" &&
    Number.isFinite(number) &&
    (source === "metric" ? metricId !== "" : itemId !== "");

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      {
        name: name.trim(),
        source_type: source,
        ...(source === "metric"
          ? { expression_id: metricId, where_sql: where.trim() || null }
          : { item_id: itemId, value_column: column.trim() || null }),
        operator,
        threshold: number,
        interval_minutes: interval,
        recipients: parseRecipients(recipients),
        renotify_hours: renotify,
        notify_on_recovery: recovery,
        enabled: true,
      },
      { onSuccess: onDone },
    );
  }

  return (
    <Card>
      <CardHeader
        title="New alert"
        description="It is checked once as soon as you save it, so a number that can't be read is refused with the reason."
      />
      <form onSubmit={submit} className="space-y-5 p-5">
        <TextField
          label="Name"
          value={name}
          maxLength={120}
          placeholder="Failed orders"
          onChange={(event) => setName(event.target.value)}
        />

        <div className="space-y-3">
          <SegmentedControl
            label="What to watch"
            value={source}
            onChange={setSource}
            options={[
              { value: "metric", label: "A shared metric" },
              { value: "item", label: "A kept answer" },
            ]}
          />
          {source === "metric" ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                label="Metric"
                value={metricId}
                options={[
                  { value: "", label: watchable.length ? "Choose a metric" : "No metrics yet" },
                  ...watchable.map((m) => ({
                    value: m.id,
                    label: `${m.name} (${m.type})`,
                  })),
                ]}
                onChange={(event) => setMetricId(event.target.value)}
              />
              <TextField
                label="Only rows where (optional)"
                value={where}
                placeholder="region = 'North'"
                onChange={(event) => setWhere(event.target.value)}
              />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                label="Kept answer"
                value={itemId}
                options={[
                  { value: "", label: kept.length ? "Choose an answer" : "Nothing kept yet" },
                  ...kept.map((k) => ({ value: k.id, label: k.title })),
                ]}
                onChange={(event) => setItemId(event.target.value)}
              />
              <TextField
                label="Column (optional)"
                hint="Leave empty to use its first number column."
                value={column}
                onChange={(event) => setColumn(event.target.value)}
              />
            </div>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <SelectField
            label="Tell me when it"
            value={operator}
            options={(Object.keys(OPERATOR_WORDS) as Operator[]).map((value) => ({
              value,
              label: OPERATOR_WORDS[value],
            }))}
            onChange={(event) => setOperator(event.target.value as Operator)}
          />
          <TextField
            label="Value"
            inputMode="decimal"
            value={threshold}
            hint="In the same unit as the metric, e.g. 3 for 3%."
            onChange={(event) => setThreshold(event.target.value)}
          />
          <SelectField
            label="Check"
            value={String(interval)}
            options={INTERVALS.map((i) => ({ value: String(i.value), label: i.label }))}
            onChange={(event) => setIntervalMinutes(Number(event.target.value))}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField
            label="If it stays that way"
            value={String(renotify)}
            options={RENOTIFY.map((r) => ({ value: String(r.value), label: r.label }))}
            onChange={(event) => setRenotify(Number(event.target.value))}
          />
          <RecipientsField
            id="alert-recipients"
            label="Also tell (you are always told)"
            value={recipients}
            onChange={setRecipients}
          />
        </div>
        <label className="flex items-center gap-2 text-[13.5px]">
          <input
            type="checkbox"
            checked={recovery}
            onChange={(event) => setRecovery(event.target.checked)}
          />
          Tell me when it is back to normal
        </label>

        {error && (
          <Notice tone="error" title="Could not save the alert">
            {error}
          </Notice>
        )}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" loading={create.isPending} disabled={!valid}>
            Create alert
          </Button>
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}

// ── One alert ────────────────────────────────────────────────────────────────

function AlertCard({ spaceId, alert }: { spaceId: string; alert: Alert }) {
  const check = useCheckAlert(spaceId);
  const update = useUpdateAlert(spaceId);
  const remove = useDeleteAlert(spaceId);
  const [cardRef, targeted] = useDeepLink("alert", alert.id);
  const [open, setOpen] = useState(targeted);
  const [confirming, setConfirming] = useState(false);
  const watched = alert.source_type === "metric" ? alert.expression_name : alert.item_title;
  const error = check.error ?? update.error ?? remove.error;

  return (
    <div ref={cardRef} className={targeted ? "deep-link-glow" : undefined}>
      <Card>
        <CardHeader
          title={
            <>
              {alert.name}
              <Badge tone={STATE_TONE[alert.state]}>{STATE_TEXT[alert.state]}</Badge>
              {!alert.enabled && <Badge tone="neutral">Paused</Badge>}
            </>
          }
          description={`Tell me when ${watched ?? "the removed source"} ${conditionText(alert)} · checked ${everyText(alert.interval_minutes)}`}
          aside={
            <div className="flex flex-wrap items-center gap-1.5">
              <Button size="sm" loading={check.isPending} onClick={() => check.mutate(alert.id)}>
                <Play aria-hidden className="size-3.5" />
                Check now
              </Button>
              <Button
                size="sm"
                variant="ghost"
                loading={update.isPending}
                onClick={() =>
                  update.mutate({ id: alert.id, changes: { enabled: !alert.enabled } })
                }
              >
                {alert.enabled ? "Pause" : "Resume"}
              </Button>
              {confirming ? (
                <>
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                    Keep
                  </Button>
                  <Button
                    size="sm"
                    className="text-danger"
                    loading={remove.isPending}
                    onClick={() => remove.mutate(alert.id)}
                  >
                    Delete
                  </Button>
                </>
              ) : (
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={`Delete ${alert.name}`}
                  onClick={() => setConfirming(true)}
                >
                  <Trash2 aria-hidden className="size-3.5" />
                </Button>
              )}
            </div>
          }
        />
        <div className="space-y-3 p-5 text-[13.5px]">
          {error && (
            <Notice tone="error" title="That didn't work">
              {asApiError(error).message}
            </Notice>
          )}
          {alert.state === "error" && alert.last_error && (
            <Notice tone="warn" title="This alert can't be checked">
              {alert.last_error}
            </Notice>
          )}
          <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-[8rem_1fr]">
            <dt className="text-subtle">Value now</dt>
            <dd className="font-medium">{valueText(alert.last_value)}</dd>
            <dt className="text-subtle">Last checked</dt>
            <dd>{alert.last_checked_at ? timeAgo(alert.last_checked_at) : "Not yet"}</dd>
            <dt className="text-subtle">Next check</dt>
            <dd>
              {alert.next_check_at && alert.enabled
                ? new Date(alert.next_check_at).toLocaleString()
                : "Not scheduled"}
            </dd>
            <dt className="text-subtle">Also tells</dt>
            <dd>{alert.recipients.length > 0 ? alert.recipients.join(", ") : "Only you"}</dd>
          </dl>
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={open}
            onClick={() => setOpen((now) => !now)}
          >
            <ChevronDown
              aria-hidden
              className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`}
            />
            What it has done
          </Button>
          {open && <Events spaceId={spaceId} alertId={alert.id} />}
        </div>
      </Card>
    </div>
  );
}

function Events({ spaceId, alertId }: { spaceId: string; alertId: string }) {
  const events = useAlertEvents(spaceId, alertId, true);
  if (events.isPending) return <Skeleton className="h-12" />;
  if (events.isError) return <p className="text-muted">{events.error.message}</p>;
  if (events.data.length === 0) return <p className="text-muted">Nothing yet.</p>;
  const LABEL = { triggered: "Went off", recovered: "Back to normal", error: "Could not check" };
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {events.data.map((event) => (
        <li key={event.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
          <span className="w-28 shrink-0 text-subtle">{timeAgo(event.at)}</span>
          <Badge
            tone={event.kind === "triggered" ? "error" : event.kind === "recovered" ? "ok" : "warn"}
          >
            {LABEL[event.kind]}
          </Badge>
          {event.value !== null && <span>{valueText(event.value)}</span>}
          {event.emailed_to.length > 0 && (
            <span className="text-subtle">emailed {event.emailed_to.length}</span>
          )}
          {event.message && <span className="text-muted">{event.message}</span>}
        </li>
      ))}
    </ul>
  );
}
