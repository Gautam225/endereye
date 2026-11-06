import type {
  ChartSpec,
  Citation,
  ChatMessage,
  Figure,
  LiveTurn,
  MessageStatus,
  ResultColumn,
  Source,
  Step,
  Thought,
} from "./types";

/** One entry per thing used, however many of its passages were found. */
export function groupSources(sources: Source[]): Source[] {
  const grouped = new Map<string, Source>();
  for (const source of sources) {
    const key = `${source.type}|${source.header}`;
    const seen = grouped.get(key);
    if (seen) seen.passages = (seen.passages ?? 1) + (source.passages ?? 1);
    else grouped.set(key, { ...source, passages: source.passages ?? 1 });
  }
  return [...grouped.values()];
}

/** What an answer card shows, whether the answer is saved or still arriving. */
export interface AnswerView {
  messageId: string | null;
  status: MessageStatus | "running";
  question: string;
  answer: string | null;
  assumptions: string[];
  trusted: boolean;
  sql: string | null;
  attempts: number;
  elapsedMs?: number;
  columns: ResultColumn[] | null;
  rows: unknown[][] | null;
  rowCount: number;
  truncated: boolean;
  chart: ChartSpec | null;
  suggestions: string[];
  options: string[];
  /** The separate analyses of a deep answer; the main result is then the first of them. */
  steps: Step[];
  sources: Source[];
  citations: Citation[];
  feedback: "up" | "down" | null;
  feedbackComment: string | null;
  error: { code: string; message: string; detail?: string } | null;
  stageLabel: string | null;
  doneStages: string[];
  thoughts: Thought[];
  figures: Figure[];
  totalMs?: number;
}

export function viewOfMessage(message: ChatMessage): AnswerView {
  return {
    messageId: message.id,
    status: message.status,
    question: message.standalone_question ?? message.question,
    answer: message.answer,
    assumptions: message.assumptions,
    trusted: message.trusted,
    sql: message.sql,
    attempts: message.attempts,
    elapsedMs: message.timings.execute,
    columns: message.columns,
    rows: message.rows,
    rowCount: message.row_count ?? 0,
    truncated: message.truncated,
    chart: message.chart,
    suggestions: message.suggestions,
    options: message.options ?? [],
    steps: message.steps ?? [],
    sources: groupSources(message.sources),
    citations: message.citations ?? [],
    feedback: message.feedback,
    feedbackComment: message.feedback_comment,
    error: message.error ? { code: message.error_code ?? "error", message: message.error } : null,
    stageLabel: null,
    doneStages: [],
    thoughts: message.thoughts ?? [],
    figures: message.figures ?? [],
    totalMs: message.timings.total,
  };
}

export function viewOfLive(turn: LiveTurn): AnswerView {
  if (turn.finished) {
    const saved = viewOfMessage(turn.finished);
    // The stream carries the failure detail that the saved message keeps shorter.
    return turn.error ? { ...saved, error: turn.error } : saved;
  }
  return {
    messageId: turn.messageId,
    status: turn.running ? "running" : turn.error ? "failed" : "cancelled",
    question: turn.question,
    answer: turn.answer,
    assumptions: [],
    trusted: false,
    sql: turn.sql,
    attempts: turn.attempt,
    elapsedMs: turn.result?.elapsed_ms,
    columns: turn.result?.columns ?? null,
    rows: turn.result?.rows ?? null,
    rowCount: turn.result?.row_count ?? 0,
    truncated: turn.result?.truncated ?? false,
    chart: turn.chart,
    suggestions: turn.suggestions,
    options: turn.options,
    steps: turn.steps,
    sources: [],
    citations: [],
    feedback: null,
    feedbackComment: null,
    error: turn.error,
    stageLabel: turn.stageLabel,
    doneStages: turn.doneStages,
    thoughts: turn.thoughts,
    figures: turn.figures,
  };
}
