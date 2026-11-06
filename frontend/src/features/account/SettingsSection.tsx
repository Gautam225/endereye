import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { cn } from "../../lib/cn";

/**
 * One page of the settings. The heading sits above a single panel; inside it, everything is a
 * row (a label on the left, its control on the right) separated by hairlines, so the eye learns
 * one pattern and keeps using it.
 */
export function SettingsSection({
  id,
  title,
  description,
  children,
  footer,
}: {
  id: string;
  title: string;
  description: string;
  children: ReactNode;
  /** A quiet line under the panel, for the thing people ask about next. */
  footer?: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`}>
      <header className="mb-5">
        <h2 id={`${id}-title`} className="text-[21px] leading-7 font-semibold tracking-[-0.01em]">
          {title}
        </h2>
        <p className="mt-1 max-w-xl text-[14px] leading-6 text-muted">{description}</p>
      </header>
      <div className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface shadow-card">
        {children}
      </div>
      {footer && <p className="mt-3 px-1 text-[13px] leading-5 text-subtle">{footer}</p>}
    </section>
  );
}

/** A setting: what it is on the left, how to change it on the right. They stack on a phone. */
export function SettingRow({
  title,
  description,
  children,
  htmlFor,
}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  /** The id of the control, so the title names it and clicking the title focuses it. */
  htmlFor?: string;
}) {
  const Title = htmlFor ? "label" : "p";
  return (
    <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
      <div className="min-w-0 sm:max-w-md">
        <Title
          {...(htmlFor ? { htmlFor } : {})}
          className="block text-[14px] leading-5 font-medium text-fg"
        >
          {title}
        </Title>
        {description && <p className="mt-0.5 text-[13px] leading-5 text-muted">{description}</p>}
      </div>
      {children !== undefined && <div className="min-w-0 shrink-0 sm:text-right">{children}</div>}
    </div>
  );
}

export interface SectionLink {
  id: string;
  label: string;
  icon: LucideIcon;
  /** A short state worth seeing without opening the section ("Paused"). */
  badge?: string;
}

/**
 * The menu of settings pages. On a wide screen it is a list down the left; on a narrow one it
 * becomes a row of buttons above the page. The current page is marked in the address, so it can
 * be linked to and survives a refresh.
 */
export function SettingsNav({ links, active }: { links: SectionLink[]; active: string }) {
  return (
    <nav aria-label="Account settings">
      <ul className="flex gap-1 overflow-x-auto pb-1 lg:sticky lg:top-8 lg:flex-col lg:overflow-visible lg:pb-0">
        {links.map(({ id, label, icon: Icon, badge }) => {
          const current = id === active;
          return (
            <li key={id} className="shrink-0">
              <Link
                to={`?section=${id}`}
                replace
                aria-current={current ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-[14px] font-medium whitespace-nowrap transition-colors",
                  "focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none",
                  current
                    ? "bg-surface-2 text-fg"
                    : "text-muted hover:bg-surface-2/60 hover:text-fg",
                )}
              >
                <Icon aria-hidden className={cn("size-4", current ? "text-fg" : "text-subtle")} />
                {label}
                {badge && (
                  <span className="ml-auto rounded-full bg-warning-soft px-2 py-0.5 text-[11px] font-medium text-warning">
                    {badge}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
