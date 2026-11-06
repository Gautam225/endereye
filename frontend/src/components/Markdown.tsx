import type { ComponentProps, ElementType, ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "../lib/cn";

type WithNode<T> = T & { node?: unknown };

/** An element with the app's own spacing and type. (`node` is react-markdown's syntax tree node.) */
function styled<T extends ElementType>(tag: T, base: string, render?: ElementType) {
  const Tag = (render ?? tag) as ElementType;
  return function Styled({ node, className, ...rest }: WithNode<ComponentProps<T>>) {
    void node;
    return <Tag className={cn(base, className as string | undefined)} {...rest} />;
  };
}

const components = {
  h1: styled("h1", "mt-6 mb-2.5 text-[18px] font-semibold tracking-[-0.01em] first:mt-0", "h2"),
  h2: styled("h2", "mt-6 mb-2 text-[16px] font-semibold tracking-[-0.01em] first:mt-0", "h3"),
  h3: styled("h3", "mt-5 mb-1.5 text-[15.5px] font-semibold first:mt-0", "h4"),
  h4: styled("h4", "mt-4 mb-1 text-[13.5px] font-semibold text-muted first:mt-0", "h5"),
  p: styled("p", "my-3 leading-[1.75] first:mt-0 last:mb-0"),
  ul: styled("ul", "my-3 list-disc space-y-1.5 pl-5 marker:text-subtle"),
  ol: styled("ol", "my-3 list-decimal space-y-1.5 pl-5 marker:text-subtle"),
  li: styled("li", "pl-1 leading-[1.7]"),
  blockquote: styled("blockquote", "my-4 border-l-2 border-border-strong pl-4 text-muted italic"),
  strong: styled("strong", "font-semibold text-fg"),
  thead: styled("thead", "bg-surface-2/70"),
  th: styled(
    "th",
    "border-b border-border px-3 py-2 text-left font-semibold whitespace-nowrap text-fg",
  ),
  td: styled("td", "border-b border-border/70 px-3 py-2 align-top tabular-nums"),
  tr: styled("tr", "even:bg-surface-2/30 last:[&>td]:border-b-0"),
  pre: styled(
    "pre",
    "my-4 overflow-x-auto rounded-lg border border-border bg-surface-2/60 p-3.5 leading-relaxed",
  ),
  hr: () => <hr className="my-6 border-border" />,
  a: ({ node, className, ...rest }: WithNode<ComponentProps<"a">>) => {
    void node;
    return (
      <a
        className={cn(
          "text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent",
          className,
        )}
        target="_blank"
        rel="noopener noreferrer"
        {...rest}
      />
    );
  },
  code: ({ node, className, children, ...rest }: WithNode<ComponentProps<"code">>) => {
    void node;
    const block = /language-/.test(className ?? "");
    return (
      <code
        className={
          block
            ? cn("font-mono text-[12.5px]", className)
            : "rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[0.88em] text-fg"
        }
        {...rest}
      >
        {children}
      </code>
    );
  },
  table: ({ node, className, ...rest }: WithNode<ComponentProps<"table">>) => {
    void node;
    return (
      <div className="my-4 overflow-x-auto rounded-lg border border-border">
        <table className={cn("w-full border-collapse text-[13px]", className)} {...rest} />
      </div>
    );
  },
};

/** Renders Markdown (headings, lists, tables, code) safely: raw HTML in the text is not run. */
export function Markdown({
  children,
  className,
  caret = false,
  renderLink,
}: {
  children: string;
  className?: string;
  /** A blinking cursor after the last word, while the text is still arriving. */
  caret?: boolean;
  /** Draws links the caller owns (an address starting "cite:"); null leaves a link ordinary. */
  renderLink?: (href: string, label: ReactNode) => ReactNode | null;
}): ReactNode {
  const own = renderLink
    ? {
        ...components,
        a: (props: WithNode<ComponentProps<"a">>) =>
          (props.href && renderLink(props.href, props.children)) || components.a(props),
      }
    : components;
  return (
    <div className={cn("text-[15.5px] leading-7 break-words text-fg", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={own}
        urlTransform={(url) => (url.startsWith("cite:") ? url : defaultUrlTransform(url))}
      >
        {children}
      </ReactMarkdown>
      {caret && (
        <span
          aria-hidden
          className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[0.15em] animate-pulse bg-accent"
        />
      )}
    </div>
  );
}
