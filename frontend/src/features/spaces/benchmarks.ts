import type { BenchmarkRun, GateResult, Outcome } from "./types";

export const OUTCOME_LABEL: Record<Outcome, string> = {
  correct: "Correct",
  incorrect: "Wrong result",
  failed: "No working query",
  not_a_query: "No query written",
  reference_error: "Reference broken",
};

export const OUTCOME_TONE: Record<Outcome, "ok" | "warn" | "error" | "neutral"> = {
  correct: "ok",
  incorrect: "error",
  failed: "error",
  not_a_query: "warn",
  reference_error: "neutral",
};

/** 0.75 -> "75%". No score until something could be judged. */
export function accuracyText(accuracy: number | null): string {
  if (accuracy === null) return "No score yet";
  return `${Math.round(accuracy * 100)}%`;
}

/** "3 of 4 correct" counts only the questions that could be judged. */
export function scoreText(
  run: Pick<BenchmarkRun, "correct" | "done" | "reference_errors">,
): string {
  const judged = run.done - run.reference_errors;
  return judged > 0 ? `${run.correct} of ${judged} correct` : "Nothing judged yet";
}

export function isActive(run: Pick<BenchmarkRun, "status"> | undefined): boolean {
  return run?.status === "running";
}

/** How often to ask the server while a run is going; false stops asking. */
export function pollInterval(run: Pick<BenchmarkRun, "status"> | undefined): number | false {
  return isActive(run) ? 1500 : false;
}

/** Share of the run that is done, for a progress bar (0 to 1). */
export function progressOf(run: Pick<BenchmarkRun, "done" | "total">): number {
  return run.total > 0 ? Math.min(1, run.done / run.total) : 0;
}

export const RUN_STATUS_TEXT: Record<BenchmarkRun["status"], string> = {
  running: "Running",
  finished: "Finished",
  failed: "Stopped early",
};

export const GATE_TEXT: Record<GateResult, string> = {
  passed: "Fit to publish",
  failed: "Accuracy dropped: do not publish",
  skipped: "Gate is off",
  no_run: "Waiting for a finished run",
};

export const GATE_TONE: Record<GateResult, "ok" | "error" | "neutral" | "warn"> = {
  passed: "ok",
  failed: "error",
  skipped: "neutral",
  no_run: "warn",
};

/** Change between two scores in percentage points, e.g. "+5 pts"; null when either is missing. */
export function changeText(now: number | null, before: number | null): string | null {
  if (now === null || before === null) return null;
  const points = Math.round((now - before) * 100);
  return points === 0 ? "no change" : `${points > 0 ? "+" : ""}${points} pts`;
}

/** SVG polyline points for scores (0 to 1) drawn left to right in a width x height box. */
export function trendPoints(scores: (number | null)[], width: number, height: number): string {
  const known = scores.flatMap((s, i) => (s === null ? [] : [[i, s] as const]));
  if (known.length === 0) return "";
  const step = scores.length > 1 ? width / (scores.length - 1) : 0;
  return known
    .map(
      ([i, s]) =>
        `${(scores.length > 1 ? i * step : width / 2).toFixed(1)},${(height - s * height).toFixed(1)}`,
    )
    .join(" ");
}
