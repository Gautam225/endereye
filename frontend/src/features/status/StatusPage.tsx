import { CircleCheck, RefreshCw, TriangleAlert } from "lucide-react";

import { PageHeader, SectionHeading } from "../../components/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { ApiError } from "../../lib/api";
import { cn } from "../../lib/cn";
import { providerLabel } from "../../lib/format";
import { DatabaseChecks } from "./DatabaseChecks";
import { ProviderCard } from "./ProviderCard";
import { useHealth, useLlmStatus } from "./queries";
import type { Health, LlmStatus } from "./types";
import { UsageTiles } from "./UsageTiles";

const CHECK_NAMES: Record<string, string> = {
  database: "PostgreSQL",
  pgvector: "pgvector",
  pg_trgm: "pg_trgm",
};

/** Plain-language list of what needs fixing, worst first. */
function findIssues(health: Health | undefined, llm: LlmStatus | undefined): string[] {
  const issues: string[] = [];
  const database = health?.checks.database;
  if (database?.status === "error") {
    issues.push(
      "PostgreSQL is not reachable, so sign-in and history won't work. " +
        "Fix: run python scripts/setup_database.py in the backend folder.",
    );
  } else if (health) {
    for (const [key, check] of Object.entries(health.checks)) {
      if (check.status !== "error") continue;
      issues.push(
        key === "schema"
          ? "The database tables are missing or out of date: run alembic upgrade head in the backend folder."
          : `${CHECK_NAMES[key] ?? key} is not installed.`,
      );
    }
  }
  if (llm) {
    if (!llm.providers.some((provider) => provider.configured)) {
      issues.push("No AI keys are configured, so nothing can be answered yet.");
    }
    for (const provider of llm.providers) {
      const name = providerLabel[provider.name] ?? provider.name;
      const disabled = provider.keys.filter((key) => key.state === "disabled").length;
      if (disabled)
        issues.push(`${disabled} ${name} key${disabled > 1 ? "s are" : " is"} disabled.`);
      const missing = provider.models.filter((model) => model.check === "missing").length;
      if (missing)
        issues.push(`${missing} ${name} model${missing > 1 ? "s are" : " is"} no longer offered.`);
    }
  }
  return issues;
}

export function StatusPage() {
  const health = useHealth();
  const llm = useLlmStatus();
  const refreshing = health.isFetching || llm.isFetching;

  const offline =
    (health.error instanceof ApiError && health.error.code === "backend_unreachable") ||
    (llm.error instanceof ApiError && llm.error.code === "backend_unreachable");

  return (
    <>
      <PageHeader
        title="System status"
        description="Health of the database and the AI providers. Refreshes every 10 seconds."
        actions={
          <Button
            onClick={() => {
              void health.refetch();
              void llm.refetch();
            }}
            disabled={refreshing}
          >
            <RefreshCw aria-hidden className={cn(refreshing && "animate-spin")} />
            Refresh
          </Button>
        }
      />

      {offline ? (
        <Notice tone="error" title="The backend is offline">
          Start it from the <code className="font-mono">backend</code> folder with{" "}
          <code className="font-mono text-fg">uvicorn app.main:app --reload</code>. This page
          reconnects by itself.
        </Notice>
      ) : (
        <div className="space-y-10">
          <Summary
            loading={health.isPending || llm.isPending}
            issues={findIssues(health.data, llm.data)}
          />
          <DatabaseChecks health={health.data} />
          <section>
            <SectionHeading
              title="AI providers"
              meta="Every call tries OpenRouter first, then Groq"
            />
            {llm.isPending ? (
              <div className="space-y-4">
                <Skeleton className="h-56 rounded-lg" />
                <Skeleton className="h-56 rounded-lg" />
              </div>
            ) : llm.isError ? (
              <Notice tone="error" title="Could not load the AI provider status">
                {llm.error.message}
              </Notice>
            ) : (
              <div className="space-y-4">
                {llm.data.providers.map((provider) => (
                  <ProviderCard key={provider.name} provider={provider} />
                ))}
              </div>
            )}
          </section>
          <UsageTiles calls={llm.data?.recent_calls} loading={llm.isPending} />
        </div>
      )}
    </>
  );
}

function Summary({ loading, issues }: { loading: boolean; issues: string[] }) {
  if (loading) return <Skeleton className="h-[84px] rounded-xl" />;
  const healthy = issues.length === 0;
  const Icon = healthy ? CircleCheck : TriangleAlert;
  return (
    <Card className={cn("rounded-xl p-5", !healthy && "border-warning/40")}>
      <div className="flex items-start gap-4">
        <span
          aria-hidden
          className={cn(
            "flex size-11 shrink-0 items-center justify-center rounded-full",
            healthy ? "bg-success-soft text-success" : "bg-warning-soft text-warning",
          )}
        >
          <Icon className="size-6" />
        </span>
        <div className="min-w-0">
          <p className="text-[16px] font-semibold">
            {healthy
              ? "All systems operational"
              : issues.length === 1
                ? "1 thing needs attention"
                : `${issues.length} things need attention`}
          </p>
          {healthy ? (
            <p className="mt-0.5 text-[13.5px] text-muted">
              The database and the AI providers are working.
            </p>
          ) : (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-[13.5px] text-muted marker:text-subtle">
              {issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Card>
  );
}
