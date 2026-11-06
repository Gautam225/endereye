export type ConnectionStatus = "untested" | "ok" | "failed" | "unsafe";
export type SslMode = "disable" | "require" | "verify-ca" | "verify-full";

/** A saved connection to an external database. The password is never sent to the browser. */
export interface Connection {
  id: string;
  name: string;
  engine: string;
  host: string;
  port: number;
  database: string;
  username: string;
  ssl_mode: SslMode;
  share_results_with_ai: boolean;
  status: ConnectionStatus;
  status_detail: string;
  server_version: string | null;
  tested_at: string | null;
  created_at: string;
  has_password: boolean;
}

/** What the form edits. `password` is only sent when something was typed. */
export interface ConnectionForm {
  name: string;
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
  ssl_mode: SslMode;
  share_results_with_ai: boolean;
}

export interface ConnectionTest {
  ok: boolean;
  status: ConnectionStatus;
  message: string;
  server_version: string | null;
  findings: string[];
  connection: Connection;
}

export interface AuditEvent {
  id: string;
  created_at: string;
  actor_name: string;
  action: string;
  target_type: string;
  target_id: string;
  target_name: string;
  detail: Record<string, unknown>;
  ip: string | null;
}
