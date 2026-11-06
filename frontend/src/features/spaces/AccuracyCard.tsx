import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { timeAgo } from "../../lib/format";
import { GATE_TEXT, GATE_TONE, accuracyText, changeText, trendPoints } from "./benchmarks";
import { useAcceptBaseline, useAccuracy, useUpdateGate } from "./queries";
import type { GateSettings } from "./types";

const CHART_WIDTH = 320;
const CHART_HEIGHT = 56;

/**
 * Accuracy over time and the release gate: with the gate on, a space whose latest score fell
 * below the accepted baseline (or below a minimum) is marked as not fit to publish.
 */
export function AccuracyCard({
  spaceId,
  latestStatus,
  selectedRunId,
}: {
  spaceId: string;
  latestStatus?: string;
  selectedRunId: string | null;
}) {
  const report = useAccuracy(spaceId, latestStatus);
  const update = useUpdateGate(spaceId);
  const accept = useAcceptBaseline(spaceId);
  const error = update.error ?? accept.error;
  const gate = report.data?.gate;
  const points = report.data?.points ?? [];
  const scores = points.map((p) => p.accuracy);
  const latest = scores.at(-1) ?? null;
  const change = changeText(latest, scores.at(-2) ?? null);
  const lastPoint = points.at(-1);

  function save(next: Partial<GateSettings>) {
    if (!gate) return;
    update.mutate({
      enabled: next.enabled ?? gate.enabled,
      max_drop: next.max_drop ?? gate.max_drop,
      min_accuracy: next.min_accuracy === undefined ? gate.min_accuracy : next.min_accuracy,
    });
  }

  return (
    <Card>
      <CardHeader
        title={
          <>
            <ShieldCheck aria-hidden className="size-4 text-accent" />
            Accuracy and release gate
          </>
        }
        description="The score of each finished run over time. Turn the gate on to block changes that make the assistant less accurate."
        aside={gate && <Badge tone={GATE_TONE[gate.result]}>{GATE_TEXT[gate.result]}</Badge>}
      />
      {report.isPending ? (
        <Skeleton className="m-5 h-20" />
      ) : report.error ? (
        <p className="p-5 text-[13px] text-muted">{report.error.message}</p>
      ) : (
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <div className="text-[26px] font-semibold tabular-nums">{accuracyText(latest)}</div>
              <div className="text-[12.5px] text-subtle">
                {lastPoint
                  ? `${change ? `${change} · ` : ""}${timeAgo(lastPoint.at)}`
                  : "No finished runs yet"}
              </div>
            </div>
            {points.length > 0 && (
              <svg
                role="img"
                aria-label={`Accuracy over the last ${points.length} runs`}
                viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
                className="h-14 w-80 max-w-full text-accent"
              >
                <polyline
                  points={trendPoints(scores, CHART_WIDTH, CHART_HEIGHT)}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </div>

          {gate && gate.reasons.length > 0 && (
            <Notice tone="error" title="Gate failed">
              {gate.reasons.join(" ")}
            </Notice>
          )}
          {error && (
            <Notice tone="error" title="Could not save">
              {asApiError(error).message}
            </Notice>
          )}

          {gate && (
            <div className="flex flex-wrap items-center gap-x-5 gap-y-3 text-[13px]">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={gate.enabled}
                  disabled={update.isPending}
                  onChange={(e) => save({ enabled: e.target.checked })}
                />
                Release gate on
              </label>
              <label className="flex items-center gap-2">
                Allowed drop
                <PercentInput
                  value={gate.max_drop}
                  disabled={update.isPending}
                  onCommit={(v) => save({ max_drop: v ?? 0 })}
                />
              </label>
              <label className="flex items-center gap-2">
                Minimum
                <PercentInput
                  value={gate.min_accuracy}
                  disabled={update.isPending}
                  onCommit={(v) => save({ min_accuracy: v })}
                />
              </label>
              <span className="text-subtle">
                Baseline:{" "}
                {gate.baseline_accuracy === null ? "none" : accuracyText(gate.baseline_accuracy)}
              </span>
              <Button
                disabled={!selectedRunId || accept.isPending}
                loading={accept.isPending}
                onClick={() => selectedRunId && accept.mutate(selectedRunId)}
              >
                Use selected run as baseline
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/** A percentage box that shows 0 to 100 and reports 0 to 1 when the person leaves it. */
function PercentInput({
  value,
  onCommit,
  disabled,
}: {
  value: number | null;
  onCommit: (value: number | null) => void;
  disabled?: boolean;
}) {
  const shown = value === null ? "" : String(Math.round(value * 100));
  const [text, setText] = useState<string | null>(null);
  return (
    <span className="flex items-center gap-1">
      <input
        inputMode="numeric"
        aria-label="Percent"
        disabled={disabled}
        value={text ?? shown}
        onChange={(e) => setText(e.target.value.replace(/[^0-9]/g, "").slice(0, 3))}
        onBlur={() => {
          if (text === null) return;
          const number = text === "" ? null : Math.min(100, Number(text)) / 100;
          setText(null);
          if (number !== value) onCommit(number);
        }}
        className="h-8 w-14 rounded-md border border-border bg-surface px-2 text-right tabular-nums"
      />
      %
    </span>
  );
}
