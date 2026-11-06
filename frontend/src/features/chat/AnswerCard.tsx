import { CircleHelp, Download, FileSpreadsheet, GitBranch, Printer, SearchX } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Button } from "../../components/ui/Button";
import { Markdown } from "../../components/Markdown";
import { Notice } from "../../components/ui/Notice";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { asApiError } from "../../lib/api";
import { count, plural } from "../../lib/format";
import { KeepButton } from "../dashboards/KeepButton";
import { DocumentViewer, type ViewTarget } from "../documents/DocumentViewer";
import { ResultTable } from "../spaces/ResultTable";
import { panelsOf, prettyName } from "./chart";
import { CitationChip, CitationList } from "./CitationList";
import { linkTags, tagOfHref, withoutTags } from "./citations";
import { ClarifyChoices } from "./ClarifyChoices";
import { ResultChart, TotalsTiles } from "./ResultChart";
import { FeedbackRow } from "./FeedbackRow";
import { FigureCard } from "./FigureCard";
import { SaveExample, SqlPanel } from "./SqlPanel";
import { VerifiedBadge } from "./VerifiedBadge";
import { ThinkingPanel } from "./ThinkingPanel";
import { printCard } from "./printReport";
import { useDownloadResult } from "./queries";
import type { AnswerView } from "./answerView";
import type { Citation } from "./types";

export function AnswerCard({
  view,
  spaceId,
  conversationId,
  editor,
  isLast,
  readOnly = false,
  onAsk,
  onStop,
  onBranch,
}: {
  view: AnswerView;
  spaceId: string;
  conversationId: string;
  editor: boolean;
  isLast: boolean;
  /** A chat someone shared: read it and open its sources, but no feedback, saving or exports. */
  readOnly?: boolean;
  onAsk: (question: string) => void;
  onStop: () => void;
  /** Start a chat of your own that continues from this answer. */
  onBranch?: (messageId: string) => void;
}) {
  const running = view.status === "running";
  const hasResult = view.columns !== null && view.rows !== null && view.columns.length > 0;
  const card = useRef<HTMLElement>(null);
  const print = () => card.current && printCard(card.current, view.question);
  const [viewing, setViewing] = useState<ViewTarget | null>(null);
  // Documents with cited pages are listed as Sources above; the rest stay in "Based on".
  const otherSources =
    view.citations.length > 0 ? view.sources.filter((s) => s.type !== "document") : view.sources;
  const cites = useMemo(() => new Map(view.citations.map((c) => [c.tag, c])), [view.citations]);
  const open = (citation: Citation) => {
    if (citation.document_id === null) return;
    setViewing({
      documentId: citation.document_id,
      title: citation.title,
      page: citation.page,
      passage: citation.text,
      section: citation.section,
      ocr: citation.ocr,
    });
  };
  const withCitations = (text: string) => (
    <Markdown
      renderLink={(href) => {
        const found = cites.get(tagOfHref(href) ?? "");
        return found ? <CitationChip citation={found} onOpen={open} /> : null;
      }}
    >
      {linkTags(text, new Set(cites.keys()))}
    </Markdown>
  );

  return (
    <article ref={card} aria-busy={running} className="space-y-5">
      <div data-no-print>
        <ThinkingPanel view={view} running={running} onStop={onStop} />
      </div>

      {view.status === "failed" && view.error && (
        <Notice tone="error" title="I couldn't answer that">
          <p>{view.error.message}</p>
          {view.error.code === "sql_failed" && (
            <p className="mt-1">
              Try asking it a different way, or name the table or column you mean.
              {editor && " You can also fix the SQL below by hand."}
            </p>
          )}
        </Notice>
      )}
      {view.status === "cancelled" && (
        <p role="status" className="text-[13.5px] text-muted">
          Stopped.
        </p>
      )}
      {view.status === "clarify" && view.answer && (
        <div className="space-y-3">
          <div className="flex gap-2.5">
            <CircleHelp aria-hidden className="mt-0.5 size-4 shrink-0 text-accent" />
            <p className="text-[14px]">{view.answer}</p>
          </div>
          {isLast && !running && view.options.length > 0 && (
            <ClarifyChoices options={view.options} onAnswer={onAsk} />
          )}
        </div>
      )}
      {view.status === "declined" && view.answer && (
        <Notice tone="info" title="This space can't answer that">
          {view.answer}
        </Notice>
      )}
      {(view.status === "ok" || view.status === "answer" || view.status === "empty") &&
        view.answer && (
          <div aria-live="polite" className="space-y-2">
            {withCitations(view.answer)}
            {view.trusted && <VerifiedBadge />}
          </div>
        )}
      {running && view.answer && <Markdown caret>{withoutTags(view.answer)}</Markdown>}

      {!running && <CitationList citations={view.citations} onOpen={open} />}
      {viewing && <DocumentViewer target={viewing} onClose={() => setViewing(null)} />}

      {view.status === "empty" && (
        <div className="flex items-start gap-2.5 rounded-md border border-border bg-surface-2/40 p-3 text-[13px] text-muted">
          <SearchX aria-hidden className="mt-0.5 size-4 shrink-0" />
          <p>
            No rows matched. Check the dates, names or filters in your question, or look at the SQL
            below to see what was asked of the data.
          </p>
        </div>
      )}

      {view.figures.map((figure, index) => (
        <FigureCard key={`${index}-${figure.title}`} figure={figure} />
      ))}

      {view.assumptions.length > 0 && (
        <p className="text-[12.5px] text-subtle">Assumed: {view.assumptions.join(" · ")}</p>
      )}

      {view.steps.length > 0 && (
        <Steps
          view={view}
          spaceId={spaceId}
          conversationId={conversationId}
          editor={editor && !running}
          onPrint={running ? undefined : print}
        />
      )}

      {hasResult && view.steps.length === 0 && view.status !== "empty" && (
        <Results
          view={view}
          spaceId={spaceId}
          conversationId={conversationId}
          saved={!running && view.messageId !== null && !readOnly}
          onPrint={print}
        />
      )}

      {view.sql && view.steps.length === 0 && (
        <SqlPanel
          spaceId={spaceId}
          sql={view.sql}
          question={view.question}
          editor={editor && !running}
          attempts={view.attempts}
          elapsedMs={view.elapsedMs}
          trusted={view.trusted}
        />
      )}

      {otherSources.length > 0 && !running && (
        <details className="text-[12.5px] text-subtle">
          <summary className="cursor-pointer">
            Based on {plural(otherSources.length, "source")}
          </summary>
          <ul className="mt-1.5 space-y-0.5 pl-4">
            {otherSources.slice(0, 10).map((source) => (
              <li key={`${source.type}-${source.header}`} className="list-disc">
                <span className="text-muted">{source.header}</span> ({source.type.replace("_", " ")}
                {(source.passages ?? 1) > 1 && `, ${source.passages} passages`})
              </li>
            ))}
          </ul>
        </details>
      )}

      {editor &&
        !running &&
        view.status === "ok" &&
        view.sql &&
        !view.trusted &&
        view.steps.length === 0 && (
          <div data-no-print>
            <SaveExample
              spaceId={spaceId}
              question={view.question}
              sql={view.sql}
              initiallyTrusted
              label="Save as a verified example"
            />
          </div>
        )}

      {!running && !readOnly && view.messageId && view.status !== "cancelled" && (
        <div data-no-print className="flex flex-wrap items-start gap-2">
          <FeedbackRow
            key={`${view.messageId}-${view.feedback}`}
            spaceId={spaceId}
            conversationId={conversationId}
            messageId={view.messageId}
            rating={view.feedback}
            comment={view.feedbackComment}
          />
          {onBranch && view.status !== "running" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onBranch(view.messageId!)}
              title="Start a new chat that begins with this conversation up to here"
            >
              <GitBranch aria-hidden className="size-3.5" />
              Branch
            </Button>
          )}
        </div>
      )}

      {isLast && !running && view.suggestions.length > 0 && (
        <div
          data-no-print
          className="flex flex-wrap gap-2 pt-1"
          aria-label="Suggested follow-up questions"
        >
          {view.suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => onAsk(suggestion)}
              className="rounded-full border border-border bg-surface-2/40 px-3 py-1.5 text-left text-[13px] transition-colors hover:border-border-strong hover:bg-surface-2"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}
    </article>
  );
}

// ── A deep answer: one section for each analysis ─────────────────────────────

/**
 * The analyses of a deep answer, each with its own plain-words summary, table or chart, and SQL.
 * One failing analysis shows its reason and leaves the others as they are.
 */
function Steps({
  view,
  spaceId,
  conversationId,
  editor,
  onPrint,
}: {
  view: AnswerView;
  spaceId: string;
  conversationId: string;
  editor: boolean;
  onPrint?: () => void;
}) {
  return (
    <div className="space-y-5">
      {onPrint && (
        <div data-no-print className="flex justify-end">
          <Button size="sm" onClick={onPrint} title="Print this report, or save it as a PDF">
            <Printer aria-hidden className="size-3.5" />
            PDF
          </Button>
        </div>
      )}
      {view.steps.map((step) => {
        const own: AnswerView = {
          ...view,
          sql: step.sql,
          columns: step.columns,
          rows: step.rows,
          rowCount: step.row_count,
          truncated: step.truncated,
          chart: step.chart,
          steps: [],
        };
        return (
          <section
            key={step.index}
            aria-label={step.title}
            className="space-y-3 rounded-lg border border-border p-4"
          >
            <h3 className="text-[14.5px] font-semibold">
              {step.index}. {step.title}
            </h3>
            {step.status === "failed" ? (
              <Notice tone="error" title="This analysis could not be completed">
                {step.error}
              </Notice>
            ) : (
              <>
                <Markdown>{step.summary}</Markdown>
                {step.columns && step.rows && step.status === "ok" && (
                  <Results
                    view={own}
                    spaceId={spaceId}
                    conversationId={conversationId}
                    saved={false}
                    onPrint={() => undefined}
                  />
                )}
              </>
            )}
            {step.sql && (
              <SqlPanel
                spaceId={spaceId}
                sql={step.sql}
                question={step.question}
                editor={editor}
                attempts={step.attempts}
                trusted={false}
              />
            )}
          </section>
        );
      })}
    </div>
  );
}

// ── Table and chart ──────────────────────────────────────────────────────────

type ResultTab = "table" | "chart";

/**
 * The result as a table, and (when the data suits one) as charts: one chart per analysis, chosen
 * from the data, with a single button to download it. There is nothing to configure.
 */
function Results({
  view,
  spaceId,
  conversationId,
  saved,
  onPrint,
}: {
  view: AnswerView;
  spaceId: string;
  conversationId: string;
  saved: boolean;
  onPrint: () => void;
}) {
  const columns = view.columns ?? [];
  const rows = view.rows ?? [];
  const [tab, setTab] = useState<ResultTab>(view.chart ? "chart" : "table");
  const csv = useDownloadResult(spaceId, conversationId, "csv");
  const excel = useDownloadResult(spaceId, conversationId, "xlsx");
  const failed = csv.error ?? excel.error;
  const problem = failed ? asApiError(failed).message : null;
  const exportable = saved && view.sql !== null && view.messageId !== null;
  const panels = view.chart ? panelsOf(view.chart, columns, rows) : [];
  const totals = view.chart?.totals ?? [];
  const omitted = view.chart?.omitted ?? [];

  return (
    <div className="space-y-3">
      <div data-no-print className="flex flex-wrap items-center gap-2">
        {view.chart && (
          <SegmentedControl
            label="Result view"
            value={tab}
            onChange={setTab}
            options={[
              { value: "chart", label: plural(panels.length, "chart") },
              { value: "table", label: "Table" },
            ]}
          />
        )}
        <p className="text-[12.5px] text-subtle">
          {plural(view.rowCount, "row")}
          {rows.length < view.rowCount && ` (first ${count(rows.length)} shown)`}
          {view.truncated && ", more than the limit"}
        </p>
        {exportable && (
          <div className="ml-auto flex items-center gap-1.5">
            <KeepButton
              spaceId={spaceId}
              conversationId={conversationId}
              messageId={view.messageId!}
            />
            <Button size="sm" loading={csv.isPending} onClick={() => csv.mutate(view.messageId!)}>
              <Download aria-hidden className="size-3.5" />
              CSV
            </Button>
            <Button
              size="sm"
              loading={excel.isPending}
              onClick={() => excel.mutate(view.messageId!)}
              title="Excel workbook with the answer and the SQL on a second sheet"
            >
              <FileSpreadsheet aria-hidden className="size-3.5" />
              Excel
            </Button>
            <Button size="sm" onClick={onPrint} title="Print this answer, or save it as a PDF">
              <Printer aria-hidden className="size-3.5" />
              PDF
            </Button>
          </div>
        )}
      </div>

      {problem && (
        <Notice tone="error" title="That didn't work">
          {problem}
        </Notice>
      )}

      {tab === "chart" && panels.length > 0 ? (
        <div className="space-y-5">
          {totals.length > 0 && <TotalsTiles totals={totals} />}
          {panels.map((panel) => (
            <ResultChart key={panel.key} spec={panel.spec} columns={columns} rows={panel.rows} />
          ))}
          {omitted.length > 0 && (
            <p className="text-[12.5px] text-subtle">
              Not charted: {omitted.map(prettyName).join(", ")}. They are in the Table view.
            </p>
          )}
        </div>
      ) : (
        <ResultTable columns={columns} rows={rows} />
      )}
    </div>
  );
}
