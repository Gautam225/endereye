export type MessageStatus =
  "running" | "ok" | "empty" | "answer" | "clarify" | "declined" | "failed" | "cancelled";

export type ReviewStatus = "open" | "resolved" | "dismissed";

export interface DayPoint {
  day: string;
  questions: number;
  failed: number;
  thumbs_down: number;
}

export interface Summary {
  days: number;
  questions: number;
  by_status: Record<string, number>;
  failure_rate: number;
  avg_total_ms: number | null;
  p95_total_ms: number | null;
  avg_execute_ms: number | null;
  thumbs_up: number;
  thumbs_down: number;
  needs_review: number;
  by_day: DayPoint[];
}

export interface Row {
  id: string;
  created_at: string;
  space_id: string;
  space_name: string;
  user_name: string;
  question: string;
  status: MessageStatus;
  error_code: string | null;
  attempts: number;
  total_ms: number | null;
  execute_ms: number | null;
  trusted: boolean;
  row_count: number | null;
  feedback: "up" | "down" | null;
  feedback_comment: string | null;
  review_status: ReviewStatus | null;
}

export interface RowList {
  total: number;
  items: Row[];
}

export interface Detail extends Row {
  conversation_id: string;
  standalone_question: string | null;
  sql: string | null;
  answer: string | null;
  assumptions: string[];
  error: string | null;
  timings: Record<string, number>;
  models: string[];
  sources: Array<{ type: string; header: string }>;
  review_note: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  feedback_at: string | null;
}

export interface Filters {
  days: number;
  status: string;
  feedback: string;
  review: string;
  spaceId: string;
  text: string;
  offset: number;
}

export interface Correction {
  question: string;
  sql: string;
  trusted: boolean;
  note: string;
}
