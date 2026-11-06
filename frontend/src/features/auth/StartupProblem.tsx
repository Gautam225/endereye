import { useEffect, useState, type ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import { InlineCode } from "../../components/ui/InlineCode";
import { Notice } from "../../components/ui/Notice";
import type { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { AuthLayout } from "./AuthLayout";

const RECHECK_MS = 5_000;

const RESTART = (
  <>
    Restart the backend: press <InlineCode>Ctrl+C</InlineCode> where it runs, then run{" "}
    <InlineCode>uvicorn app.main:app --reload</InlineCode>.
  </>
);

/** What went wrong, in plain words, and the exact steps that fix it. */
const PROBLEMS: Record<string, { title: string; steps: ReactNode[] }> = {
  database_unavailable: {
    title: "Can't connect to the database",
    steps: [
      <>
        In the <InlineCode>backend</InlineCode> folder, run{" "}
        <InlineCode>python scripts/setup_database.py</InlineCode>. It asks for your PostgreSQL
        password once, then sets up the login, the databases, and the tables, and saves the settings
        in <InlineCode>.env</InlineCode>.
      </>,
      RESTART,
    ],
  },
  database_not_ready: {
    title: "The database tables need updating",
    steps: [
      <>
        In the <InlineCode>backend</InlineCode> folder, run{" "}
        <InlineCode>alembic upgrade head</InlineCode>.
      </>,
    ],
  },
  backend_unreachable: {
    title: "The backend is not running",
    steps: [
      <>
        In the <InlineCode>backend</InlineCode> folder, with <InlineCode>.venv</InlineCode> active,
        run <InlineCode>uvicorn app.main:app --reload</InlineCode>.
      </>,
    ],
  },
};

function reasonOf(error: ApiError): string | null {
  const reason = (error.details as { reason?: unknown } | null)?.reason;
  if (typeof reason === "string") return reason;
  return error.code === "backend_unreachable" ? null : error.message;
}

/** Full-screen "can't start" page. It checks again every few seconds by itself. */
export function StartupProblem({ error }: { error: ApiError }) {
  const { retry, checking } = useAuth();
  const [clicked, setClicked] = useState(false);
  const known = PROBLEMS[error.code];
  const reason = reasonOf(error);

  useEffect(() => {
    const timer = window.setInterval(retry, RECHECK_MS);
    return () => window.clearInterval(timer);
  }, [retry]);

  return (
    <AuthLayout
      wide
      title={known?.title ?? "Eye of Ender can't start"}
      description="Fix this and the page continues by itself."
    >
      <div className="space-y-6">
        {reason && (
          <Notice tone="error" title="What happened">
            {reason}
          </Notice>
        )}
        {known && (
          <ol className="space-y-3">
            {known.steps.map((step, index) => (
              <li key={index} className="flex gap-3">
                <span
                  aria-hidden
                  className="mt-px flex size-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent"
                >
                  {index + 1}
                </span>
                <span className="leading-relaxed text-muted">{step}</span>
              </li>
            ))}
          </ol>
        )}
        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
          {/* Only a click shows the spinner; the silent background checks don't flicker. */}
          <Button
            onClick={() => {
              setClicked(true);
              retry();
            }}
            loading={clicked && checking}
          >
            Check again
          </Button>
          <span className="text-[13px] text-subtle">Also checks by itself every 5 seconds.</span>
        </div>
      </div>
    </AuthLayout>
  );
}
