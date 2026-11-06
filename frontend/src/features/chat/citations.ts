import type { Citation } from "./types";

// A tag as the AI writes it: [S1], several as [S1, S2], or in the full-width brackets 【S1】 that
// some models use.
const GROUP = /[[【]\s*(S\d{1,2}(?:\s*[,;、]\s*S\d{1,2})*)\s*[\]】]/g;
const TAG = /S\d{1,2}/g;

/** An answer with its citation tags removed (while it is still arriving, before they can be linked). */
export function withoutTags(text: string): string {
  return text.replace(new RegExp(`[ \\t]?${GROUP.source}`, "g"), "");
}

/** The answer's tags as links the Markdown can turn into buttons. A tag with no passage behind it
 * (the AI made it up) is dropped rather than shown as something to click. */
export function linkTags(text: string, known: ReadonlySet<string>): string {
  return text.replace(GROUP, (_all, group: string) =>
    (group.match(TAG) ?? [])
      .filter((tag) => known.has(tag))
      .map((tag) => `[${tag.slice(1)}](cite:${tag})`)
      .join(""),
  );
}

/** "policy, page 4", or the section for a file without pages, or just the title. */
export function where(citation: Pick<Citation, "title" | "page" | "section">): string {
  if (citation.page !== null) return `${citation.title}, page ${citation.page}`;
  if (citation.section) return `${citation.title} › ${citation.section}`;
  return citation.title;
}

/** The tag a link made by `linkTags` points at, or null for any other link. */
export function tagOfHref(href: string | undefined): string | null {
  return href?.startsWith("cite:") ? href.slice(5) : null;
}

/** What the chip after a sentence says: the document and the page ("Refund policy · p. 2"). */
export function chipText(citation: Pick<Citation, "title" | "page" | "section">): string {
  if (citation.page !== null) return `${citation.title} · p. ${citation.page}`;
  return citation.section ? `${citation.title} › ${citation.section}` : citation.title;
}
