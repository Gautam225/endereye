import { ArrowRight } from "lucide-react";
import { Link } from "react-router";

import { Badge } from "../../components/ui/Status";
import { Skeleton } from "../../components/ui/Skeleton";
import { useMailStatus, useRecipients } from "../mail/queries";
import { SettingRow, SettingsSection } from "./SettingsSection";

const GO =
  "inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface px-3 text-[13px] font-medium text-fg shadow-card transition-colors hover:border-border-strong hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none";

/** A summary of email, with the way to the Email page where it is managed. */
export function EmailSection() {
  const recipients = useRecipients();
  const status = useMailStatus();
  const count = recipients.data?.length ?? 0;

  return (
    <SettingsSection
      id="addresses"
      title="Email"
      description="Who your reports and alerts are sent to, and whether email is ready to send them."
    >
      <SettingRow
        title="People you send to"
        description={
          recipients.isPending
            ? undefined
            : count === 0
              ? "No one saved yet."
              : `${count} ${count === 1 ? "person" : "people"} saved, one click away when you make a report or alert.`
        }
      >
        {recipients.isPending ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <Link to="/email" className={GO}>
            Manage
            <ArrowRight aria-hidden className="size-3.5" />
          </Link>
        )}
      </SettingRow>
      <SettingRow
        title="Sending email"
        description={
          status.data?.configured
            ? `Sent from ${status.data.from_address || "the server's email account"}.`
            : "Not set up yet. Reports and alerts are made but not emailed."
        }
      >
        {status.isPending ? (
          <Skeleton className="h-6 w-16" />
        ) : (
          <Badge tone={status.data?.configured ? "ok" : "warn"}>
            {status.data?.configured ? "Ready" : "Not set up"}
          </Badge>
        )}
      </SettingRow>
    </SettingsSection>
  );
}
