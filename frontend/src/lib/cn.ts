/** Join class names, skipping empty ones: cn("a", isOn && "b") */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
