import { Boxes } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { Link, Navigate, useNavigate } from "react-router";

import { PageHeader } from "../../components/PageHeader";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { SelectField } from "../../components/ui/Field";
import { Skeleton } from "../../components/ui/Skeleton";
import { cn } from "../../lib/cn";
import { lastSpace, rememberSpace } from "../chat/lastSpace";
import { useSpaces } from "../spaces/queries";

export type Section = "dashboards" | "reports" | "alerts";

const SECTIONS: Array<{ id: Section; label: string }> = [
  { id: "dashboards", label: "Dashboards" },
  { id: "reports", label: "Reports" },
  { id: "alerts", label: "Alerts" },
];

/**
 * The top of the Dashboards and Reports pages: which space, and which of the two. Both are
 * kept per space, because the answers come from that space's data.
 */
export function SpaceTabs({
  spaceId,
  section,
  title,
  description,
  actions,
  children,
}: {
  spaceId: string;
  section: Section;
  title: string;
  description: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const spaces = useSpaces();
  const choices = (spaces.data ?? []).filter((s) => !s.is_personal);

  useEffect(() => {
    rememberSpace(spaceId);
  }, [spaceId]);

  return (
    <div className="w-full">
      <PageHeader title={title} description={description} actions={actions} />
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <nav aria-label="Dashboards, reports and alerts" className="flex gap-1">
          {SECTIONS.map((s) => (
            <Link
              key={s.id}
              to={`/spaces/${spaceId}/${s.id}`}
              aria-current={s.id === section ? "page" : undefined}
              className={cn(
                "rounded-lg px-3 py-1.5 text-[13.5px] font-medium transition-colors",
                s.id === section
                  ? "bg-surface-2 text-fg"
                  : "text-muted hover:bg-surface-2/60 hover:text-fg",
              )}
            >
              {s.label}
            </Link>
          ))}
        </nav>
        {choices.length > 1 && (
          <SelectField
            label="Space"
            hideLabel
            className="w-56"
            value={spaceId}
            options={choices.map((s) => ({ value: s.id, label: s.name }))}
            onChange={(event) => navigate(`/spaces/${event.target.value}/${section}`)}
          />
        )}
      </div>
      {children}
    </div>
  );
}

/** Where "Dashboards" and "Reports" in the menu lead: the space last used, or the first one. */
export function SpaceRedirect({ section }: { section: Section }) {
  const spaces = useSpaces();
  if (spaces.isPending) {
    return (
      <div className="mx-auto max-w-2xl space-y-3 p-8">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-24" />
      </div>
    );
  }
  if (spaces.isError) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <Notice tone="error" title="Could not open this page">
          {spaces.error.message}
        </Notice>
      </div>
    );
  }
  const choices = spaces.data.filter((s) => !s.is_personal);
  const remembered = choices.find((s) => s.id === lastSpace());
  const target = remembered ?? choices[0];
  if (!target) {
    return (
      <div className="mx-auto max-w-2xl p-8">
        <EmptyState icon={Boxes} title="No spaces yet">
          Dashboards and reports are made from a space's data. Create or join a space first.
        </EmptyState>
      </div>
    );
  }
  return <Navigate to={`/spaces/${target.id}/${section}`} replace />;
}
