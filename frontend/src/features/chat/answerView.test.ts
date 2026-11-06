import { describe, expect, it } from "vitest";

import { groupSources, viewOfLive, viewOfMessage } from "./answerView";
import type { ChatMessage, LiveTurn } from "./types";

describe("groupSources", () => {
  it("lists a document once however many passages of it were used", () => {
    const grouped = groupSources([
      { type: "document", header: "Silverline" },
      { type: "document", header: "Crestview" },
      { type: "document", header: "Silverline" },
      { type: "document", header: "Silverline" },
    ]);

    expect(grouped).toEqual([
      { type: "document", header: "Silverline", passages: 3 },
      { type: "document", header: "Crestview", passages: 1 },
    ]);
  });

  it("adds up passage counts the server already grouped, and keeps types apart", () => {
    const grouped = groupSources([
      { type: "document", header: "Rules", passages: 2 },
      { type: "table", header: "Rules", passages: 1 },
      { type: "document", header: "Rules", passages: 3 },
    ]);

    expect(grouped).toEqual([
      { type: "document", header: "Rules", passages: 5 },
      { type: "table", header: "Rules", passages: 1 },
    ]);
  });

  it("does not change what it was given", () => {
    const given = [{ type: "document", header: "A" }];
    groupSources(given);
    expect(given).toEqual([{ type: "document", header: "A" }]);
  });
});

describe("a deep answer", () => {
  const step = {
    index: 1,
    title: "Revenue by region",
    question: "What is the revenue of each region?",
    sql: "SELECT 1",
    status: "ok" as const,
    summary: "4 rows.",
    columns: [{ name: "revenue", type: "DOUBLE" }],
    rows: [[1]],
    row_count: 1,
    truncated: false,
    chart: null,
    attempts: 1,
    assumptions: [],
  };

  it("keeps its analyses in order, whether saved or still arriving", () => {
    const base = {
      id: "m1",
      seq: 1,
      question: "q",
      status: "ok",
      sources: [],
      citations: [],
      timings: {},
      assumptions: [],
      suggestions: [],
    } as unknown as ChatMessage;

    expect(viewOfMessage({ ...base, steps: [step] }).steps).toEqual([step]);
    expect(viewOfMessage(base).steps).toEqual([]); // an answer saved before deep mode existed
    const live = { question: "q", running: true, steps: [step, { ...step, index: 2 }] };
    expect(viewOfLive(live as unknown as LiveTurn).steps.map((s) => s.index)).toEqual([1, 2]);
  });
});
