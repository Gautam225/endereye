import { Database, MessageSquareText, ShieldCheck } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, type ReactNode } from "react";

import { BrandMark } from "../../components/BrandMark";
import { ThemeSwitcher } from "../../components/ThemeSwitcher";

const POINTS = [
  {
    icon: MessageSquareText,
    title: "Ask in plain English",
    text: "No SQL needed. Type a question and get a table or a chart back.",
  },
  {
    icon: Database,
    title: "Answers you can check",
    text: "Every answer shows the exact query behind it, so you can trust the numbers.",
  },
  {
    icon: ShieldCheck,
    title: "Your data stays yours",
    text: "Runs on your own servers. People only see the data they have been given.",
  },
];

/** Centered card for sign-in, setup, and full-screen states. */
export function AuthLayout({
  title,
  description,
  children,
  footer,
  wide = false,
  showcase = false,
}: {
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  /** Wider column, for pages with instructions rather than a short form. */
  wide?: boolean;
  /** A panel beside the form that says what the app is for (large screens only). */
  showcase?: boolean;
}) {
  useEffect(() => {
    document.title = `${title} · Eye of Ender`;
  }, [title]);

  const card = (
    <motion.div
      className={wide ? "w-full max-w-[560px]" : "w-full max-w-[400px]"}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="mb-7 space-y-1.5">
        <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.02em]">{title}</h1>
        {description && <p className="text-[15px] text-muted">{description}</p>}
      </div>
      {children}
      {footer && <div className="mt-7 text-[13px] text-subtle">{footer}</div>}
    </motion.div>
  );

  if (!showcase) {
    return (
      <div className="flex min-h-dvh flex-col">
        <header className="flex items-center justify-between px-5 py-4 sm:px-8">
          <Brand />
          <ThemeSwitcher />
        </header>
        <main className="flex flex-1 items-start justify-center px-5 pt-[8vh] pb-16 sm:items-center sm:pt-0">
          {card}
        </main>
      </div>
    );
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <aside className="relative hidden overflow-hidden border-r border-border bg-surface lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-60"
          style={{
            backgroundImage:
              "radial-gradient(60% 50% at 20% 0%, color-mix(in srgb, var(--accent) 22%, transparent), transparent 70%), linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)",
            backgroundSize: "auto, 44px 44px, 44px 44px",
            maskImage: "linear-gradient(to bottom, black 20%, transparent 95%)",
          }}
        />
        <div className="relative">
          <Brand />
        </div>
        <div className="relative max-w-md space-y-9">
          <h2 className="text-[34px] leading-[1.15] font-semibold tracking-[-0.025em]">
            Your data, answered in plain English.
          </h2>
          <ul className="space-y-6">
            {POINTS.map(({ icon: Icon, title: heading, text }) => (
              <li key={heading} className="flex gap-4">
                <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2 text-accent">
                  <Icon aria-hidden className="size-[18px]" />
                </span>
                <div>
                  <p className="font-medium">{heading}</p>
                  <p className="text-[14px] leading-relaxed text-muted">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-[12.5px] text-subtle">Eye of Ender</p>
      </aside>

      <div className="flex min-h-dvh flex-col">
        <header className="flex items-center justify-between px-5 py-4 sm:px-8">
          <div className="lg:invisible">
            <Brand />
          </div>
          <ThemeSwitcher />
        </header>
        <main className="flex flex-1 items-start justify-center px-5 pt-[6vh] pb-16 sm:items-center sm:pt-0">
          {card}
        </main>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <BrandMark />
      <span className="text-[15px] font-semibold tracking-[-0.01em]">Eye of Ender</span>
    </div>
  );
}
