import { BadgeCheck } from "lucide-react";

/** The answer came from a query an editor checked and saved as Trusted. */
export function VerifiedBadge() {
  return (
    <span
      title="This answer used a query that an editor verified and saved as an example"
      className="inline-flex items-center gap-1 rounded-full border border-success/30 bg-success-soft px-2 py-0.5 text-[12px] font-medium text-success"
    >
      <BadgeCheck aria-hidden className="size-3.5" />
      Verified query
    </span>
  );
}
