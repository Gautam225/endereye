import { Check, ClipboardList, X } from "lucide-react";
import { useState } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { BareTextArea, SelectField, TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { milliseconds, plural, timeAgo } from "../../lib/format";
import { useCorrect, useDetail, useReview } from "./queries";
import { STATUS_LABEL, STATUS_TONE } from "./status";
import type { Detail, ReviewStatus } from "./types";

const REVIEW_OPTIONS: Array<{ value: ReviewStatus; label: string }> = [
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed (nothing to fix)" },
  { value: "open", label: "Open (needs a fix)" },
];

/** One answer in detail, with the tools to review it and to save a verified correction. */
export function ReviewPanel({ id, onClose }: { id: string | null; onClose: () => void }) {
  const detail = useDetail(id);

  if (id === null) {
    return (
      <Card className="overflow-hidden rounded-xl">
        <EmptyState icon={ClipboardList} title="Pick a question">
          See its SQL, what went wrong, and what the person said. Then mark it reviewed, or save a
          verified correction as an example.
        </EmptyState>
      </Card>
    );
  }
  if (detail.isPending) return <Skeleton className="h-96" />;
  if (detail.isError) {
    return (
      <Notice tone="error" title="Could not load this answer">
        {detail.error.message}
      </Notice>
    );
  }
  return <Body key={detail.data.id} detail={detail.data} onClose={onClose} />;
}

function Body({ detail, onClose }: { detail: Detail; onClose: () => void }) {
  return (
    <Card className="overflow-hidden rounded-xl">
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[detail.status]}>{STATUS_LABEL[detail.status]}</Badge>
            {detail.feedback && (
              <Badge tone={detail.feedback === "down" ? "warn" : "ok"}>
                Thumbs {detail.feedback}
              </Badge>
            )}
          </span>
        }
        description={`${detail.space_name} · ${detail.user_name} · ${timeAgo(detail.created_at)}`}
        aside={
          <Button variant="ghost" size="icon" aria-label="Close" onClick={onClose}>
            <X aria-hidden />
          </Button>
        }
      />
      <div className="max-h-[calc(100vh-14rem)] space-y-4 overflow-y-auto p-5">
        <Field label="Question">
          <p className="text-[14px]">{detail.question}</p>
          {detail.standalone_question && detail.standalone_question !== detail.question && (
            <p className="text-[12.5px] text-subtle">Understood as: {detail.standalone_question}</p>
          )}
        </Field>

        {detail.error && (
          <Notice tone="error" title={detail.error_code ?? "Error"}>
            {detail.error}
          </Notice>
        )}
        {detail.answer && (
          <Field label="Answer given">
            <p className="text-[13.5px] whitespace-pre-wrap">{detail.answer}</p>
          </Field>
        )}
        {detail.feedback_comment && (
          <Field label="What the person said">
            <p className="text-[13.5px]">“{detail.feedback_comment}”</p>
          </Field>
        )}
        {detail.sql && (
          <Field label="SQL">
            <pre className="max-h-60 overflow-auto rounded-md bg-surface-2/60 px-3 py-2 font-mono text-[12.5px] whitespace-pre-wrap">
              {detail.sql}
            </pre>
          </Field>
        )}
        {detail.assumptions.length > 0 && (
          <p className="text-[12.5px] text-subtle">Assumed: {detail.assumptions.join(" · ")}</p>
        )}
        <p className="text-[12.5px] text-subtle">
          {Object.entries(detail.timings)
            .map(([stage, ms]) => `${stage.replace("_", " ")} ${milliseconds(ms)}`)
            .join(" · ")}
          {detail.models.length > 0 && ` · ${detail.models.join(", ")}`}
          {detail.row_count !== null && ` · ${plural(detail.row_count, "row")}`}
        </p>

        <ReviewForm detail={detail} />
        <CorrectionForm detail={detail} />
      </div>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-[12.5px] font-medium text-muted">{label}</p>
      {children}
    </div>
  );
}

function ReviewForm({ detail }: { detail: Detail }) {
  const review = useReview(detail.id);
  const [status, setStatus] = useState<ReviewStatus>(detail.review_status ?? "resolved");
  const [note, setNote] = useState(detail.review_note ?? "");
  const error = review.error ? asApiError(review.error).message : null;

  return (
    <section className="space-y-3 rounded-lg border border-border p-3">
      <h4 className="text-[13.5px] font-semibold">Review</h4>
      {detail.review_status && (
        <p className="text-[12.5px] text-subtle">
          Currently {detail.review_status}
          {detail.reviewed_by && ` by ${detail.reviewed_by}`}
          {detail.reviewed_at && `, ${timeAgo(detail.reviewed_at)}`}.
        </p>
      )}
      {error && (
        <Notice tone="error" title="Not saved">
          {error}
        </Notice>
      )}
      <SelectField
        label="Outcome"
        value={status}
        options={REVIEW_OPTIONS}
        onChange={(event) => setStatus(event.target.value as ReviewStatus)}
      />
      <TextField
        label="Note (optional)"
        maxLength={2000}
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className="flex items-center justify-end gap-3">
        {review.isSuccess && (
          <p role="status" className="flex items-center gap-1.5 text-[13px] text-muted">
            <Check aria-hidden className="size-4 text-success" />
            Saved
          </p>
        )}
        <Button
          variant="primary"
          loading={review.isPending}
          onClick={() => review.mutate({ status, note: note.trim() })}
        >
          Save review
        </Button>
      </div>
    </section>
  );
}

function CorrectionForm({ detail }: { detail: Detail }) {
  const correct = useCorrect(detail.id);
  const [question, setQuestion] = useState(detail.standalone_question ?? detail.question);
  const [sql, setSql] = useState(detail.sql ?? "");
  const [trusted, setTrusted] = useState(false);
  const [note, setNote] = useState("");
  const error = correct.error ? asApiError(correct.error).message : null;

  return (
    <section className="space-y-3 rounded-lg border border-border p-3">
      <h4 className="text-[13.5px] font-semibold">Save a verified correction</h4>
      <p className="text-[12.5px] text-subtle">
        Write the SQL that answers this question properly. It is checked and run first; only a query
        that works becomes an example, and the review is marked resolved. What people said in
        feedback is never used as SQL.
      </p>
      {error && (
        <Notice tone="error" title="Not saved">
          {error}
        </Notice>
      )}
      <TextField
        label="Question, as a person would ask it"
        maxLength={500}
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
      />
      <div className="space-y-1.5">
        <label htmlFor={`fix-${detail.id}`} className="block text-[13px] font-medium">
          Corrected SQL
        </label>
        <BareTextArea
          id={`fix-${detail.id}`}
          rows={5}
          spellCheck={false}
          className="font-mono text-[13px]"
          value={sql}
          onChange={(event) => setSql(event.target.value)}
        />
      </div>
      <TextField
        label="When is it especially relevant? (optional)"
        maxLength={1000}
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <label className="flex items-center gap-2 text-[13px] text-muted">
        <input
          type="checkbox"
          checked={trusted}
          onChange={(event) => setTrusted(event.target.checked)}
          className="size-3.5 accent-[var(--color-accent)]"
        />
        I have checked the result (mark as Trusted)
      </label>
      <div className="flex items-center justify-end gap-3">
        {correct.data && (
          <p role="status" className="flex items-center gap-1.5 text-[13px] text-muted">
            <Check aria-hidden className="size-4 text-success" />
            Saved. The SQL ran and returned {plural(correct.data.row_count, "row")}.
          </p>
        )}
        <Button
          variant="primary"
          loading={correct.isPending}
          disabled={!question.trim() || !sql.trim()}
          onClick={() =>
            correct.mutate({
              question: question.trim(),
              sql: sql.trim(),
              trusted,
              note: note.trim(),
            })
          }
        >
          Verify and save as example
        </Button>
      </div>
    </section>
  );
}
