import { CircleCheck, Mail, TriangleAlert, UsersRound } from "lucide-react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router";

import { FadeSwitch } from "../../components/FadeSwitch";
import { PageHeader } from "../../components/PageHeader";
import { Button } from "../../components/ui/Button";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/cn";
import { PeopleSection } from "./PeopleSection";
import { useMailSettings, useMailStatus, type MailStatus } from "./queries";
import { SendingAccount } from "./SendingAccount";

type Tab = "people" | "account";

/**
 * Everything about email in one place. Everyone keeps the people they send to here; an
 * administrator also sets up the account the emails go out from.
 */
export function MailPage() {
  const { hasRole } = useAuth();
  const admin = hasRole("admin");
  const status = useMailStatus();
  const [params, setParams] = useSearchParams();
  const tab: Tab = admin && params.get("tab") === "account" ? "account" : "people";
  const go = (next: Tab) => setParams(next === "people" ? {} : { tab: next }, { replace: true });

  return (
    <>
      <PageHeader
        title="Email"
        description={
          admin
            ? "Choose who reports and alerts go to, and set up the account they are sent from."
            : "Choose who your reports and alerts go to. Saved addresses show up as one-click choices."
        }
      />
      <div className="space-y-6">
        <Banner
          admin={admin}
          status={status.data}
          loading={status.isPending}
          onSetUp={() => go("account")}
        />

        {admin && (
          <div role="tablist" aria-label="Email" className="flex gap-1 border-b border-border">
            <TabButton active={tab === "people"} onClick={() => go("people")} icon={<UsersRound />}>
              People you send to
            </TabButton>
            <TabButton active={tab === "account"} onClick={() => go("account")} icon={<Mail />}>
              Sending account
            </TabButton>
          </div>
        )}

        <div role="tabpanel">
          <FadeSwitch id={tab}>{tab === "people" ? <PeopleSection /> : <Account />}</FadeSwitch>
        </div>
      </div>
    </>
  );
}

function Account() {
  const mail = useMailSettings();
  if (mail.isPending) return <Skeleton className="h-72" />;
  if (mail.isError) {
    return (
      <Notice tone="error" title="Could not load the email settings">
        {mail.error.message}
      </Notice>
    );
  }
  return <SendingAccount mail={mail.data} />;
}

/** The first thing anyone needs to know: can this app send email right now? */
function Banner({
  admin,
  status,
  loading,
  onSetUp,
}: {
  admin: boolean;
  status: MailStatus | undefined;
  loading: boolean;
  onSetUp: () => void;
}) {
  if (loading) return <Skeleton className="h-20" />;
  if (status?.configured) {
    return (
      <div className="flex items-center gap-4 rounded-lg border border-success/30 bg-success-soft p-4">
        <CircleCheck aria-hidden className="size-6 shrink-0 text-success" />
        <div className="min-w-0">
          <p className="font-medium">Email is ready</p>
          <p className="text-[13.5px] text-muted">
            Reports and alerts are sent
            {status.from_address ? (
              <>
                {" "}
                from <b className="font-medium text-fg">{status.from_address}</b>
              </>
            ) : null}
            .
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-4 rounded-lg border border-warning/30 bg-warning-soft p-4">
      <TriangleAlert aria-hidden className="size-6 shrink-0 text-warning" />
      <div className="min-w-0 flex-1">
        <p className="font-medium">Email is not set up yet</p>
        <p className="text-[13.5px] text-muted">
          Your reports and alerts are still made, but nobody is emailed until this is done.
          {admin ? "" : " Please ask an administrator to set it up."}
        </p>
      </div>
      {admin && (
        <Button variant="primary" onClick={onSetUp}>
          Set it up now
        </Button>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "-mb-px flex items-center gap-2 border-b-2 px-3.5 py-2.5 text-[14px] font-medium transition-colors [&>svg]:size-4",
        active ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg",
      )}
    >
      {icon}
      {children}
    </button>
  );
}
