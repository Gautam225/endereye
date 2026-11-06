const EMAIL = /^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/;

/** Addresses typed or pasted in one box: separated by commas, semicolons, spaces or new lines.
 * "Name <a@b.com>" (as copied from a mail program) counts as a@b.com. Repeats are dropped. */
export function parseEmails(text: string): { valid: string[]; invalid: string[] } {
  const valid: string[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();
  const pieces = text
    .replace(/<([^>]*)>/g, " $1 ")
    .split(/[\s,;]+/)
    .filter(Boolean);
  for (const piece of pieces) {
    const email = piece.toLowerCase();
    if (!EMAIL.test(email)) invalid.push(piece);
    else if (!seen.has(email)) {
      seen.add(email);
      valid.push(email);
    }
  }
  return { valid, invalid };
}
