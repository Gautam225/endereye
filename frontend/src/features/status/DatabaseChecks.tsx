import { Boxes, Database, Table2, TextSearch, type LucideIcon } from "lucide-react";

import { SectionHeading } from "../../components/PageHeader";
import { Card } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { StatusLabel } from "../../components/ui/Status";
import { milliseconds } from "../../lib/format";
import type { CheckResult, Health } from "./types";

interface Check {
  key: string;
  label: string;
  purpose: string;
  icon: LucideIcon;
  versionLabel: (version: string) => string;
}

const CHECKS: Check[] = [
  {
    key: "database",
    label: "PostgreSQL",
    purpose: "App data and chat history",
    icon: Database,
    versionLabel: (v) => `v${v}`,
  },
  {
    key: "pgvector",
    label: "pgvector",
    purpose: "Vector search for RAG",
    icon: Boxes,
    versionLabel: (v) => `v${v}`,
  },
  {
    key: "pg_trgm",
    label: "pg_trgm",
    purpose: "Fuzzy matching of values",
    icon: TextSearch,
    versionLabel: (v) => `v${v}`,
  },
  {
    key: "schema",
    label: "Tables",
    purpose: "Schema migrations",
    icon: Table2,
    versionLabel: (v) => `migration ${v}`,
  },
];

export function DatabaseChecks({ health }: { health: Health | undefined }) {
  return (
    <section>
      <SectionHeading title="Database" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {CHECKS.map(({ key, ...check }) => (
          <CheckTile key={key} {...check} result={health?.checks[key]} />
        ))}
      </div>
    </section>
  );
}

function CheckTile({
  label,
  purpose,
  icon: Icon,
  versionLabel,
  result,
}: Omit<Check, "key"> & { result: CheckResult | undefined }) {
  return (
    <Card className="flex flex-col gap-3 rounded-xl p-4">
      <div className="flex items-center gap-3">
        <span
          aria-hidden
          className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted ring-1 ring-border"
        >
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] leading-tight font-semibold">{label}</p>
          <p className="truncate text-[12.5px] text-subtle">{purpose}</p>
        </div>
      </div>
      <div className="mt-auto flex items-center justify-between gap-3 border-t border-border pt-3">
        {result ? (
          <StatusLabel tone={result.status === "ok" ? "ok" : "error"}>
            {result.status === "ok" ? "Healthy" : "Problem"}
          </StatusLabel>
        ) : (
          <Skeleton className="h-4 w-16" />
        )}
        {result?.status === "ok" && (
          <p className="font-mono text-[12px] text-subtle">
            {result.version ? versionLabel(result.version) : ""}
            {result.latency_ms !== null && ` · ${milliseconds(result.latency_ms)}`}
          </p>
        )}
      </div>
      {result?.status === "error" && result.detail && (
        <p className="rounded-md bg-danger-soft px-2.5 py-2 text-[12.5px] break-words text-fg">
          {result.detail}
        </p>
      )}
    </Card>
  );
}
