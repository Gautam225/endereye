import type { DocumentInfo } from "./types";

/** Formats whose pages a citation can name. */
const PAGED = [".pdf", ".pptx"];

/** A document read before page numbers were kept: reading it again adds them. */
export function needsReread(
  document: Pick<DocumentInfo, "filename" | "status" | "page_count">,
): boolean {
  const name = document.filename.toLowerCase();
  return (
    document.status === "ready" &&
    document.page_count === null &&
    PAGED.some((extension) => name.endsWith(extension))
  );
}

/** Page numbers as a person would write them: [1, 2, 3, 7, 9, 10] becomes "1–3, 7, 9–10". */
export function pageRanges(pages: number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b);
  const parts: string[] = [];
  for (let i = 0; i < sorted.length;) {
    let end = i;
    while (sorted[end + 1] === (sorted[end] ?? 0) + 1) end++;
    parts.push(end > i ? `${sorted[i]}–${sorted[end]}` : `${sorted[i]}`);
    i = end + 1;
  }
  return parts.join(", ");
}

/** "page 4" or "pages 4–6", for a sentence. */
export function pagesText(pages: number[]): string {
  return `${pages.length === 1 ? "page" : "pages"} ${pageRanges(pages)}`;
}
