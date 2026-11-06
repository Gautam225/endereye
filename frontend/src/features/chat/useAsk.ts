import { useCallback, useEffect, useRef, useState } from "react";

import { apiGetStream, apiPostStream, apiSend, asApiError } from "../../lib/api";
import { readSse } from "../../lib/sse";
import type {
  ChartSpec,
  ChatMessage,
  Figure,
  LiveTurn,
  Mention,
  ResultColumn,
  Step,
  Thought,
} from "./types";
import type { AnswerStyle } from "./answerStyle";

const NEW_TURN = (question: string, replaceSeq: number | null, mentions: Mention[]): LiveTurn => ({
  question,
  thoughts: [],
  figures: [],
  mentions,
  replaceSeq,
  messageId: null,
  running: true,
  stage: null,
  stageLabel: null,
  doneStages: [],
  sql: null,
  attempt: 0,
  result: null,
  answer: null,
  chart: null,
  suggestions: [],
  options: [],
  steps: [],
  error: null,
  finished: null,
});

type Handler = (turn: LiveTurn, data: Record<string, unknown>) => LiveTurn;

/** How each event from the server changes what the screen shows. */
const HANDLERS: Record<string, Handler> = {
  start: (turn, data) => ({ ...turn, messageId: String(data.message_id) }),
  status: (turn, data) => ({
    ...turn,
    doneStages: turn.stage ? [...turn.doneStages, turn.stage] : turn.doneStages,
    stage: String(data.stage),
    stageLabel: String(data.message),
  }),
  sql: (turn, data) => ({ ...turn, sql: String(data.sql), attempt: Number(data.attempt) }),
  rows: (turn, data) => ({
    ...turn,
    result: {
      columns: data.columns as ResultColumn[],
      rows: data.rows as unknown[][],
      row_count: Number(data.row_count),
      truncated: Boolean(data.truncated),
      elapsed_ms: Number(data.elapsed_ms),
    },
  }),
  thought: (turn, data) => ({ ...turn, thoughts: [...turn.thoughts, data as unknown as Thought] }),
  "answer.delta": (turn, data) => ({ ...turn, answer: (turn.answer ?? "") + String(data.text) }),
  figure: (turn, data) => ({ ...turn, figures: [...turn.figures, data as unknown as Figure] }),
  answer: (turn, data) => ({ ...turn, answer: String(data.text) }),
  chart: (turn, data) => ({ ...turn, chart: data as unknown as ChartSpec }),
  suggestions: (turn, data) => ({ ...turn, suggestions: data.questions as string[] }),
  options: (turn, data) => ({ ...turn, options: data.options as string[] }),
  step: (turn, data) => ({ ...turn, steps: [...turn.steps, data as unknown as Step] }),
  error: (turn, data) => ({
    ...turn,
    error: {
      code: String(data.code),
      message: String(data.message),
      detail: data.detail ? String(data.detail) : undefined,
    },
  }),
  done: (turn, data) => ({
    ...turn,
    running: false,
    stage: null,
    stageLabel: null,
    finished: data as unknown as ChatMessage,
  }),
};

/**
 * Sends a question and follows the answer as it streams in (start, status, sql, rows, answer,
 * chart, suggestions, title, error, done). Stop ends it on the server too.
 */
export function useAsk(spaceId: string) {
  const [live, setLive] = useState<LiveTurn | null>(null);
  const controller = useRef<AbortController | null>(null);
  const target = useRef<{ conversationId: string; messageId: string | null } | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  /**
   * Follows one answer's event stream into `live`. The answer runs on the server on its own, so
   * leaving or refreshing the page does not stop it: `resume` rejoins it from the start.
   */
  const follow = useCallback(
    async (
      conversationId: string,
      first: LiveTurn,
      open: (signal: AbortSignal) => Promise<Response>,
    ) => {
      controller.current?.abort();
      const mine = new AbortController();
      controller.current = mine;
      target.current = { conversationId, messageId: null };
      // A newer question replaces this one; late events from this one must not touch the screen.
      const update = (change: (turn: LiveTurn) => LiveTurn) => {
        if (controller.current === mine) setLive((turn) => (turn ? change(turn) : turn));
      };

      setLive(first);
      try {
        const response = await open(mine.signal);
        for await (const message of readSse(response.body!)) {
          let data: Record<string, unknown>;
          try {
            data = JSON.parse(message.data) as Record<string, unknown>;
          } catch {
            continue;
          }
          if (message.event === "start" && target.current) {
            target.current.messageId = String(data.message_id);
          }
          const handler = HANDLERS[message.event];
          if (handler) update((turn) => handler(turn, data));
        }
        update((turn) => (turn.running ? { ...turn, running: false } : turn));
      } catch (caught) {
        if (mine.signal.aborted) {
          update((turn) => ({ ...turn, running: false }));
          return;
        }
        const error = asApiError(caught);
        update((turn) => ({
          ...turn,
          running: false,
          error: { code: error.code, message: error.message },
        }));
      }
    },
    [],
  );

  const ask = useCallback(
    (
      conversationId: string,
      question: string,
      options: {
        replaceMessageId?: string;
        replaceSeq?: number;
        mentions?: Mention[];
        mode?: AnswerStyle;
      } = {},
    ) => {
      const mentions = options.mentions ?? [];
      return follow(
        conversationId,
        NEW_TURN(question, options.replaceSeq ?? null, mentions),
        (signal) =>
          apiPostStream(
            `/spaces/${spaceId}/conversations/${conversationId}/messages`,
            {
              question,
              replace_message_id: options.replaceMessageId ?? null,
              mentions: mentions.map((m) => m.id),
              mode: options.mode ?? "standard",
            },
            signal,
          ),
      );
    },
    [spaceId, follow],
  );

  /** Rejoin an answer that was still being written when the page was refreshed. */
  const resume = useCallback(
    (conversationId: string, message: ChatMessage) =>
      follow(conversationId, NEW_TURN(message.question, message.seq, message.mentions), (signal) =>
        apiGetStream(
          `/spaces/${spaceId}/conversations/${conversationId}/messages/${message.id}/events`,
          signal,
        ),
      ),
    [spaceId, follow],
  );

  const stop = useCallback(() => {
    const current = target.current;
    controller.current?.abort();
    if (current?.messageId) {
      // The server also notices the closed connection; this stops a running query at once.
      void apiSend<void>(
        "POST",
        `/spaces/${spaceId}/conversations/${current.conversationId}/messages/${current.messageId}/cancel`,
      ).catch(() => undefined);
    }
  }, [spaceId]);

  const clear = useCallback(() => setLive(null), []);

  return { live, ask, resume, stop, clear };
}
