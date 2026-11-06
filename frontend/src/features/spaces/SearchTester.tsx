import { ChevronDown, DatabaseZap, RefreshCw, Search } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { count } from "../../lib/format";
import { useIndexStatus, useRebuildIndex, useSearchTest } from "./queries";
import type { SearchHit, SearchPassage } from "./types";

const TYPE_LABEL: Record<string, string> = {
  table: "Table",
  column: "Column",
  instruction: "Instruction",
  glossary: "Glossary",
  example_sql: "Example SQL",
  document: "Document",
};

/** Ask a question and see exactly what the AI would be shown, and how each piece ranked. */
export function SearchTester({ spaceId }: { spaceId: string }) {
  const search = useSearchTest(spaceId);
  const [question, setQuestion] = useState("");
  const error = search.error ? asApiError(search.error).message : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (question.trim()) search.mutate(question.trim());
  }

  return (
    <Card>
      <CardHeader
        title="Search tester"
        description="Type a question as a person would ask it. This shows what the AI would be given to answer it: the best few pieces of your tables, rules, examples and documents."
      />
      <div className="space-y-4 p-5">
        <IndexLine spaceId={spaceId} />
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <div className="min-w-60 flex-1">
            <TextField
              label="Question"
              placeholder="e.g. what is the return window?"
              maxLength={1000}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
          </div>
          <Button
            type="submit"
            variant="primary"
            loading={search.isPending}
            disabled={!question.trim()}
          >
            <Search aria-hidden className="size-3.5" />
            Search
          </Button>
        </form>
        {error && (
          <Notice tone="error" title="Search failed">
            {error}
          </Notice>
        )}
        {search.data &&
          (search.data.hits.length === 0 ? (
            <p role="status" className="text-[13px] text-muted">
              Nothing is indexed in this space yet. Add tables, instructions or documents first.
            </p>
          ) : (
            <Results result={search.data} />
          ))}
      </div>
    </Card>
  );
}

function IndexLine({ spaceId }: { spaceId: string }) {
  const status = useIndexStatus(spaceId);
  const rebuild = useRebuildIndex(spaceId);
  if (!status.data) return null;
  const parts = Object.entries(status.data.chunks)
    .map(([type, n]) => `${count(n)} ${(TYPE_LABEL[type] ?? type).toLowerCase()}`)
    .join(" · ");
  const failure = rebuild.error ? asApiError(rebuild.error).message : null;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted">
        <DatabaseZap aria-hidden className="size-3.5 shrink-0" />
        <span>{parts ? `Indexed: ${parts}` : "Nothing indexed yet"}</span>
        {status.data.failed_documents > 0 && (
          <Badge tone="warn">{status.data.failed_documents} document could not be read</Badge>
        )}
        <Button
          size="sm"
          variant="ghost"
          loading={rebuild.isPending}
          onClick={() => rebuild.mutate()}
          title={`Read everything again. Use it after changing a model or chunk setting (${status.data.chunk_tokens} tokens per chunk, ${status.data.embedding_model}).`}
        >
          <RefreshCw aria-hidden className="size-3.5" />
          Rebuild
        </Button>
      </div>
      {rebuild.data && (
        <p role="status" className="text-[12.5px] text-muted">
          {rebuild.data.added + rebuild.data.updated + rebuild.data.removed === 0
            ? "Already up to date."
            : `Rebuilt: ${rebuild.data.added} added, ${rebuild.data.updated} changed, ${rebuild.data.removed} removed.`}
        </p>
      )}
      {failure && (
        <Notice tone="error" title="Rebuild failed">
          {failure}
        </Notice>
      )}
    </div>
  );
}

function Results({
  result,
}: {
  result: { passages: SearchPassage[]; hits: SearchHit[]; timings_ms: Record<string, number> };
}) {
  const total = Object.values(result.timings_ms).reduce((a, b) => a + b, 0);
  return (
    <div className="space-y-4">
      <div>
        <p className="mb-2 text-[13px] font-medium">
          The AI would be shown {result.passages.length}{" "}
          <span className="font-normal text-subtle">(found in {total} ms)</span>
        </p>
        <ol className="space-y-2">
          {result.passages.map((passage, index) => (
            <PassageCard key={passage.chunk_ids.join("-")} passage={passage} index={index + 1} />
          ))}
        </ol>
      </div>
      <details className="group rounded-md border border-border">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[13px] font-medium">
          <ChevronDown
            aria-hidden
            className="size-4 text-subtle transition-transform group-open:rotate-180"
          />
          How each candidate ranked ({result.hits.length})
        </summary>
        <StageTable hits={result.hits} />
      </details>
    </div>
  );
}

function PassageCard({ passage, index }: { passage: SearchPassage; index: number }) {
  const sql = typeof passage.meta.sql === "string" ? passage.meta.sql : null;
  return (
    <li className="rounded-md border border-border bg-surface-2/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-subtle tabular-nums">#{index}</span>
        <Badge tone="accent">{TYPE_LABEL[passage.source_type] ?? passage.source_type}</Badge>
        {passage.meta.trusted === true && <Badge tone="ok">Trusted</Badge>}
        <span className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{passage.header}</span>
        <span className="text-[12px] text-subtle tabular-nums">score {passage.score}</span>
      </div>
      <p className="mt-1.5 text-[13px] whitespace-pre-wrap">{passage.text}</p>
      {sql && (
        <pre className="mt-2 overflow-x-auto rounded-md bg-surface px-3 py-2 font-mono text-[12.5px] whitespace-pre-wrap">
          {sql}
        </pre>
      )}
    </li>
  );
}

function StageTable({ hits }: { hits: SearchHit[] }) {
  return (
    <div
      className="max-h-96 overflow-auto border-t border-border"
      tabIndex={0}
      role="region"
      aria-label="Ranking at each stage"
    >
      <table className="w-full border-collapse text-[12.5px]">
        <thead className="sticky top-0 bg-surface text-left text-subtle">
          <tr>
            {["Kept", "Piece", "Vector", "Keyword", "Fused", "Rerank"].map((heading) => (
              <th key={heading} scope="col" className="px-3 py-1.5 font-medium">
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {hits.map((hit) => (
            <tr
              key={hit.id}
              className={cn("border-t border-border", hit.final_rank !== null && "bg-accent/5")}
            >
              <td className="px-3 py-1.5 tabular-nums">
                {hit.final_rank ? `#${hit.final_rank}` : ""}
              </td>
              <td className="max-w-80 px-3 py-1.5">
                <span className="block truncate font-mono">
                  {TYPE_LABEL[hit.source_type] ?? hit.source_type}: {hit.header}
                </span>
                <span className="block truncate text-subtle">{hit.snippet}</span>
              </td>
              <td className="px-3 py-1.5 tabular-nums">{hit.vector_rank ?? "-"}</td>
              <td className="px-3 py-1.5 tabular-nums">{hit.bm25_rank ?? "-"}</td>
              <td className="px-3 py-1.5 tabular-nums">{hit.fused_rank ?? "-"}</td>
              <td className="px-3 py-1.5 tabular-nums">{hit.rerank_score ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
