/** Toggles an answer on or off in the list of ticked ones, keeping the order they were offered in. */
export function toggleChoice(selected: string[], option: string, offered: string[]): string[] {
  const next = selected.includes(option)
    ? selected.filter((item) => item !== option)
    : [...selected, option];
  return offered.filter((item) => next.includes(item));
}

/**
 * The message to send for a question the assistant asked: the answers that were picked, then
 * whatever the person typed. "Total revenue" + "only for 2025" -> "Total revenue. Only for 2025".
 * Several picked answers are joined with a semicolon. Empty when nothing was picked or typed.
 */
export function composeReply(selected: string[], typed: string): string {
  const picked = selected
    .map((item) => item.trim())
    .filter(Boolean)
    .join("; ");
  const own = typed.trim();
  if (!picked) return own;
  if (!own) return picked;
  const joined = /[.!?]$/.test(picked) ? picked : `${picked}.`;
  return `${joined} ${own.charAt(0).toUpperCase()}${own.slice(1)}`;
}
