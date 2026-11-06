/** Good enough to tell a typo from an address; the server checks it properly. */
export function isEmail(text: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text.trim());
}

export interface ParsedAddresses {
  /** Addresses that look right, in lower case, each once. */
  valid: string[];
  /** Things that were typed but are not an address. */
  invalid: string[];
}

/**
 * Addresses pasted in any way people write them: commas, semicolons, spaces or line breaks
 * between them, and "Name <name@company.com>" as copied from a mail program.
 */
export function parseAddresses(text: string): ParsedAddresses {
  const valid = new Set<string>();
  const invalid: string[] = [];
  for (const raw of text.split(/[\n,;]+/)) {
    const part = raw.trim();
    if (part === "") continue;
    const angle = /<([^<>]+)>/.exec(part);
    const pieces = angle ? [angle[1]!] : part.split(/\s+/);
    for (const piece of pieces) {
      const candidate = piece.trim().replace(/^["']|["']$/g, "");
      if (candidate === "") continue;
      if (isEmail(candidate)) valid.add(candidate.toLowerCase());
      else invalid.push(candidate);
    }
  }
  return { valid: [...valid], invalid };
}

/**
 * Turns what a mail server says into something a person can act on. The server's own words are
 * kept for anything not listed, so nothing is hidden.
 */
export function friendlyMailError(message: string, provider: string): string {
  const text = message.toLowerCase();
  if (text.includes("refused the sign-in") || text.includes("authentication")) {
    return provider === "gmail"
      ? "Gmail did not accept that password. Use an app password (a 16-letter code from your Google account), not your normal Gmail password."
      : "The mail server did not accept that email address and password. Check both and try again.";
  }
  if (text.includes("could not be reached") || text.includes("timed out")) {
    return "The mail server could not be reached. Check the server name and port under Advanced settings, and that this computer is online.";
  }
  if (text.includes("refused the recipients")) {
    return "The mail server refused the address it was asked to send to.";
  }
  return message;
}
