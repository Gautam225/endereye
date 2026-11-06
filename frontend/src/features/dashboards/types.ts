import type { ChartSpec, ResultColumn } from "../chat/types";

/** An answer kept on a dashboard: refreshed by running its SQL again. */
export interface KeptItem {
  id: string;
  dashboard_id: string;
  title: string;
  question: string;
  sql: string;
  chart: ChartSpec | null;
  position: number;
  columns: ResultColumn[] | null;
  rows: unknown[][] | null;
  row_count: number | null;
  truncated: boolean;
  refreshed_at: string | null;
  /** Why the last refresh failed; the old result is still shown. */
  refresh_error: string;
  created_at: string;
}

export interface Dashboard {
  id: string;
  space_id: string;
  name: string;
  created_at: string;
  items: KeptItem[];
}

export interface PinInput {
  conversationId: string;
  messageId: string;
  dashboardId?: string;
  title?: string;
}

export type Frequency = "daily" | "weekly" | "monthly";
export type ReportFormat = "pdf" | "xlsx" | "both";

export interface ReportRun {
  id: string;
  trigger: "schedule" | "manual";
  status: "running" | "ok" | "failed";
  error: string;
  files: string[];
  emailed_to: string[];
  started_at: string;
  finished_at: string | null;
}

export interface ReportSchedule {
  frequency: Frequency;
  hour: number;
  minute: number;
  /** Days of a weekly report, Monday is 0 and Sunday is 6. */
  weekdays: number[];
  day_of_month: number;
  timezone: string;
}

export interface Report extends ReportSchedule {
  id: string;
  space_id: string;
  name: string;
  item_ids: string[];
  /** The kept answers it holds, named. */
  items: Array<{ id: string; title: string }>;
  format: ReportFormat;
  recipients: string[];
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run: ReportRun | null;
  created_at: string;
}

export interface ReportInput extends ReportSchedule {
  name: string;
  item_ids: string[];
  format: ReportFormat;
  recipients: string[];
  enabled: boolean;
}

export interface ReportOptions {
  email_configured: boolean;
  allowed_domains: string[];
  max_recipients: number;
}

/** A kept answer in a list to choose from: no result rows, so a long list stays light. */
export interface KeptSummary {
  id: string;
  title: string;
  question: string;
  dashboard_name: string;
}

export interface KeptPage {
  total: number;
  items: KeptSummary[];
}
