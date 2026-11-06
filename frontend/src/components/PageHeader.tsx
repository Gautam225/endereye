import { useEffect, type ReactNode } from "react";

/** The top of a page: its name, a line about it, and the main actions, over a thin rule. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  useEffect(() => {
    document.title = `${title} · Eye of Ender`;
  }, [title]);

  return (
    <header className="mb-8 flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-1.5">
        <h1 className="text-[24px] leading-tight font-semibold tracking-[-0.015em]">{title}</h1>
        {description && <p className="max-w-2xl text-[14px] leading-6 text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2 sm:pt-0.5">{actions}</div>}
    </header>
  );
}

export function SectionHeading({ title, meta }: { title: string; meta?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      {meta && <div className="text-[13px] text-subtle">{meta}</div>}
    </div>
  );
}
