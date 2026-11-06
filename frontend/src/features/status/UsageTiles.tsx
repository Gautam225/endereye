import { Activity, CircleCheck, CircleX, Gauge } from "lucide-react";

import { SectionHeading } from "../../components/PageHeader";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { StatTile } from "../../components/ui/StatTile";
import type { RecentCalls } from "./types";

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

export function UsageTiles({
  calls,
  loading,
}: {
  calls: RecentCalls | null | undefined;
  loading: boolean;
}) {
  const failures = calls
    ? calls.total - (calls.by_outcome.ok ?? 0) - (calls.by_outcome.rate_limited ?? 0)
    : 0;
  return (
    <section>
      <SectionHeading title="AI calls" meta="Last 24 hours, every attempt counted" />
      {loading ? (
        <div className="grid gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[88px] rounded-lg" />
          ))}
        </div>
      ) : calls ? (
        <div className="grid gap-3 sm:grid-cols-4">
          <StatTile label="Attempts" icon={Activity} value={compact.format(calls.total)} />
          <StatTile
            label="Succeeded"
            icon={CircleCheck}
            tone="ok"
            value={compact.format(calls.by_outcome.ok ?? 0)}
          />
          <StatTile
            label="Rate-limited"
            icon={Gauge}
            tone={(calls.by_outcome.rate_limited ?? 0) > 0 ? "warn" : "default"}
            value={compact.format(calls.by_outcome.rate_limited ?? 0)}
          />
          <StatTile
            label="Other failures"
            icon={CircleX}
            tone={failures > 0 ? "danger" : "default"}
            value={compact.format(failures)}
          />
        </div>
      ) : (
        <Notice title="Call history is unavailable">
          It is stored in PostgreSQL. Fix the database problem above and it will appear here.
        </Notice>
      )}
    </section>
  );
}
