import { MIN_PASSWORD } from "../auth/rules";

export interface Strength {
  /** 0 (nothing typed) to 4. */
  level: 0 | 1 | 2 | 3 | 4;
  label: string;
}

/**
 * How strong a new password looks. Length is what counts (the same rule as the server's minimum),
 * so a long sentence beats a short jumble of symbols; a single repeated character never counts.
 */
export function passwordStrength(password: string): Strength {
  if (password.length === 0) return { level: 0, label: "" };
  if (/^(.)\1*$/.test(password)) return { level: 1, label: "Too predictable" };
  if (password.length < MIN_PASSWORD) return { level: 1, label: "Too short" };
  if (password.length < 14) return { level: 2, label: "Okay" };
  if (password.length < 20) return { level: 3, label: "Good" };
  return { level: 4, label: "Strong" };
}
