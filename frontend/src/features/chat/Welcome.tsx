import { ArrowUpRight } from "lucide-react";
import { useState } from "react";

import { BrandMark } from "../../components/BrandMark";
import { Button } from "../../components/ui/Button";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { useAuth } from "../../lib/auth";
import { AnswerStyleMenu } from "./AnswerStyleMenu";
import { Composer, type ComposerFiles } from "./Composer";
import { looksLikeSearch } from "./intent";
import { useDiscover, useSuggestions } from "./queries";
import type { DiscoverHit } from "./types";

const TYPE_LABEL: Record<DiscoverHit["type"], string> = {
  table: "Table",
  column: "Column",
  glossary: "Term",
  document: "Document",
  example_sql: "Example question",
};

/** What to try in the general chat. */
const GENERAL_IDEAS = [
  "Explain how a SQL join works",
  "Help me write a short email to my team",
  "Summarise the document I attached",
  "What are good ways to present sales data?",
];

function greeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

/** The empty chat: a greeting, the question box and a few starting points. */
export function Welcome({
  spaceId,
  spaceName,
  personal,
  files,
  onAsk,
}: {
  spaceId: string;
  spaceName: string;
  /** The general chat: no tables, only documents added to the chat. */
  personal: boolean;
  files: ComposerFiles;
  onAsk: (question: string) => void;
}) {
  const { user } = useAuth();
  // What was typed is a search when it clearly asks to find a table, column, term or document;
  // anything else is a question. The results say so and offer to ask it instead.
  const [searched, setSearched] = useState("");
  const firstName = user?.full_name.split(" ")[0];
  const searching = searched !== "" && !personal;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center px-4 pt-10 pb-24">
        <div className="mb-7">
          <BrandMark className="mb-5 size-9 text-muted" />
          <p className="text-[15px] text-muted">
            {greeting(new Date().getHours())}
            {firstName ? `, ${firstName}` : ""}
          </p>
          <h1 className="mt-1 text-[28px] leading-tight font-semibold tracking-[-0.02em]">
            What would you like to know?
          </h1>
          <p className="mt-2 text-[14px] leading-6 text-subtle">
            {personal ? (
              <>
                This is the general chat: ask anything, or attach documents with the paperclip and
                ask about them. To ask about a space's data, pick it at the top.
              </>
            ) : (
              <>
                Ask about the data in <span className="font-medium text-muted">{spaceName}</span> in
                plain words. You get the answer, the table, a chart and the SQL.
              </>
            )}
          </p>
        </div>

        <Composer
          autoFocus
          running={false}
          onStop={() => undefined}
          files={files}
          placeholder={
            personal
              ? "Ask anything, or attach a document and ask about it. Type @ to point at one"
              : "Ask a question about the data, or find a table, column or term"
          }
          onSend={(text) => {
            if (!personal && looksLikeSearch(text)) setSearched(text.trim());
            else onAsk(text);
          }}
          trailing={<AnswerStyleMenu deep={!personal} />}
        />

        {personal ? (
          <Ideas items={GENERAL_IDEAS} onAsk={onAsk} />
        ) : searching ? (
          <SearchResults
            spaceId={spaceId}
            text={searched}
            onAsk={onAsk}
            onClear={() => setSearched("")}
          />
        ) : (
          <Suggestions spaceId={spaceId} onAsk={onAsk} />
        )}
      </div>
    </div>
  );
}

function Cards({ items, onAsk }: { items: string[]; onAsk: (question: string) => void }) {
  return (
    <section className="mt-7" aria-labelledby="try-asking">
      <h2
        id="try-asking"
        className="mb-2.5 text-[11px] font-semibold tracking-wide text-subtle uppercase"
      >
        Try asking
      </h2>
      <ul className="grid gap-2 sm:grid-cols-2">
        {items.map((question) => (
          <li key={question}>
            <button
              type="button"
              onClick={() => onAsk(question)}
              className="group flex h-full w-full items-start gap-3 rounded-xl border border-border bg-surface px-3.5 py-3 text-left text-[13.5px] leading-5 text-muted transition-colors hover:border-border-strong hover:bg-surface-2/60 hover:text-fg"
            >
              <span className="flex-1">{question}</span>
              <ArrowUpRight
                aria-hidden
                className="mt-0.5 size-4 shrink-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100"
              />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Ideas({ items, onAsk }: { items: string[]; onAsk: (question: string) => void }) {
  return <Cards items={items} onAsk={onAsk} />;
}

function Suggestions({ spaceId, onAsk }: { spaceId: string; onAsk: (question: string) => void }) {
  const suggestions = useSuggestions(spaceId);
  if (suggestions.isPending) return <Skeleton className="mt-6 h-16" />;
  const items = suggestions.data ?? [];
  return items.length === 0 ? null : <Cards items={items} onAsk={onAsk} />;
}

/** What the space holds that matches, with a way back if the words were really a question. */
function SearchResults({
  spaceId,
  text,
  onAsk,
  onClear,
}: {
  spaceId: string;
  text: string;
  onAsk: (question: string) => void;
  onClear: () => void;
}) {
  return (
    <section className="mt-6" aria-label="Search results">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="min-w-0 flex-1 truncate text-[13px] text-muted">
          Looking for <span className="font-medium text-fg">{text}</span>
        </p>
        <Button size="sm" variant="ghost" onClick={() => onAsk(text)}>
          Ask it as a question instead
        </Button>
        <Button size="sm" variant="ghost" onClick={onClear}>
          Clear
        </Button>
      </div>
      <SearchHits spaceId={spaceId} text={text} onAsk={onAsk} />
    </section>
  );
}

function SearchHits({
  spaceId,
  text,
  onAsk,
}: {
  spaceId: string;
  text: string;
  onAsk: (question: string) => void;
}) {
  const results = useDiscover(spaceId, text);
  if (results.isPending) return <Skeleton className="mt-6 h-24" />;
  if (results.isError) {
    return (
      <Notice tone="error" title="Search failed" className="mt-6">
        {results.error.message}
      </Notice>
    );
  }
  if (results.data.length === 0) {
    return (
      <p role="status" className="mt-6 text-[13px] text-muted">
        Nothing in this space matches that. Try other words, or ask a question instead.
      </p>
    );
  }
  return (
    <ul className="mt-6 divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
      {results.data.map((hit) => (
        <li key={`${hit.type}-${hit.title}`} className="flex items-start gap-3 px-4 py-3">
          <div className="min-w-0 flex-1 space-y-0.5">
            <p className="flex items-center gap-2 text-[14px] font-medium">
              <Badge tone="neutral">{TYPE_LABEL[hit.type]}</Badge>
              <span className="truncate">{hit.title}</span>
            </p>
            <p className="line-clamp-2 text-[13px] text-muted">{hit.snippet}</p>
          </div>
          <Button
            size="sm"
            onClick={() =>
              onAsk(hit.type === "example_sql" ? hit.title : `Tell me about ${hit.title}`)
            }
          >
            Ask
          </Button>
        </li>
      ))}
    </ul>
  );
}
