/**
 * Whether what someone typed is a look-up of what the space contains ("find the salary table",
 * "which columns have dates") rather than a question about the data. Only clear look-ups count:
 * "find the highest paid employee" is a question, so a data question is never held up as a search.
 */
const WHAT = String.raw`(?:tables?|columns?|fields?|terms?|definitions?|documents?|docs?|files?)`;
const LOOKUP = [
  // find / search / look up / locate ... (a few words) ... a table, column, term or document
  new RegExp(
    String.raw`^\s*(?:find|search|look\s?up|locate)\s+(?:for\s+)?(?:(?:the|a|an|any|all)\s+)?(?:\w+\s+){0,2}${WHAT}\b`,
    "i",
  ),
  // which / what tables ... , list the columns, show me all tables
  new RegExp(String.raw`^\s*(?:which|what)\s+${WHAT}\b`, "i"),
  new RegExp(String.raw`^\s*(?:list|show)\s+(?:me\s+)?(?:(?:all|the)\s+)?${WHAT}\b`, "i"),
];

export function looksLikeSearch(text: string): boolean {
  const words = text.trim().split(/\s+/).length;
  return words <= 12 && LOOKUP.some((pattern) => pattern.test(text));
}
