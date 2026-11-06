import { CalendarClock, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { EmailNotice } from "./EmailNotice";
import { NewReport } from "./NewReport";
import { ReportCard } from "./ReportCard";
import { SpaceTabs } from "./SpaceTabs";
import { useKeptItems, useReportOptions, useReports } from "./queries";

/**
 * Reports: kept answers that are run on a schedule and sent as a PDF or an Excel file. A report
 * runs as you, so it holds only what you may read.
 */
export function ReportsPage() {
  const { spaceId = "" } = useParams();
  const reports = useReports(spaceId);
  const options = useReportOptions(spaceId);
  const kept = useKeptItems(spaceId, "");
  const [creating, setCreating] = useState(false);
  const keptTotal = kept.data?.pages[0]?.total ?? 0;

  return (
    <SpaceTabs
      spaceId={spaceId}
      section="reports"
      title="Reports"
      description="Send answers you kept to yourself or others on a schedule, as a PDF or an Excel file. Each report runs as you, so it only holds what you are allowed to see."
      actions={
        <Button variant="primary" onClick={() => setCreating(true)} disabled={creating}>
          <Plus aria-hidden />
          New report
        </Button>
      }
    >
      <div className="space-y-5">
        {options.data && !options.data.email_configured && (
          <EmailNotice>
            Reports are still made on schedule and can be downloaded here, but they are not sent.
          </EmailNotice>
        )}
        {creating && (
          <NewReport spaceId={spaceId} options={options.data} onDone={() => setCreating(false)} />
        )}
        {reports.isPending ? (
          <Skeleton className="h-32" />
        ) : reports.isError ? (
          <Notice tone="error" title="Could not load your reports">
            {reports.error.message}
          </Notice>
        ) : reports.data.length === 0 && !creating ? (
          <Card>
            <EmptyState icon={CalendarClock} title="No reports yet">
              {keptTotal === 0 ? (
                <>
                  A report is made of answers you kept. Keep one from a chat first, in{" "}
                  <Link
                    to={`/spaces/${spaceId}/dashboards`}
                    className="text-accent underline-offset-2 hover:underline"
                  >
                    Dashboards
                  </Link>
                  .
                </>
              ) : (
                "Choose New report to send your kept answers on a schedule."
              )}
            </EmptyState>
          </Card>
        ) : (
          reports.data.map((report) => (
            <ReportCard key={report.id} spaceId={spaceId} report={report} />
          ))
        )}
      </div>
    </SpaceTabs>
  );
}
