import type { AuditEvent, Connection, ConnectionForm, ConnectionStatus, SslMode } from "./types";

export const STATUS_LABEL: Record<ConnectionStatus, string> = {
  untested: "Not tested",
  ok: "Working, read-only",
  failed: "Could not connect",
  unsafe: "Blocked: not read-only",
};

export const STATUS_TONE: Record<ConnectionStatus, "ok" | "warn" | "error" | "neutral"> = {
  untested: "neutral",
  ok: "ok",
  failed: "error",
  unsafe: "error",
};

export const SSL_OPTIONS: Array<{ value: SslMode; label: string }> = [
  { value: "verify-full", label: "Encrypted, certificate and host name checked (recommended)" },
  { value: "verify-ca", label: "Encrypted, certificate checked" },
  { value: "require", label: "Encrypted, server not verified" },
  { value: "disable", label: "Not encrypted (only on a trusted private network)" },
];

export function emptyForm(): ConnectionForm {
  return {
    name: "",
    host: "",
    port: "5432",
    database: "",
    username: "",
    password: "",
    ssl_mode: "verify-full",
    share_results_with_ai: false,
  };
}

export function formFromConnection(connection: Connection): ConnectionForm {
  return {
    name: connection.name,
    host: connection.host,
    port: String(connection.port),
    database: connection.database,
    username: connection.username,
    password: "",
    ssl_mode: connection.ssl_mode,
    share_results_with_ai: connection.share_results_with_ai,
  };
}

/** What the server refuses in a host: a URL, a user@, a path, spaces. */
const PLAIN_HOST = /^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$|^[0-9A-Fa-f:.]{2,45}$/;
const IDENTIFIER = /^[A-Za-z0-9_.$-]+$/;

export type FormProblems = Partial<Record<keyof ConnectionForm, string>>;

/** The same checks the server makes, so mistakes show up before saving. */
export function problemsIn(form: ConnectionForm, editing: boolean): FormProblems {
  const problems: FormProblems = {};
  if (!form.name.trim()) problems.name = "Give the connection a name.";
  if (!PLAIN_HOST.test(form.host.trim())) {
    problems.host = "Use a plain host name or address, without http://, a user name or a path.";
  }
  const port = Number(form.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    problems.port = "Use a port from 1 to 65535.";
  }
  if (!IDENTIFIER.test(form.database.trim())) {
    problems.database = "Use letters, digits and _ . $ - only.";
  }
  if (!IDENTIFIER.test(form.username.trim())) {
    problems.username = "Use letters, digits and _ . $ - only.";
  }
  if (!editing && !form.password) problems.password = "Enter the password of this login.";
  return problems;
}

/** The body for a new connection. */
export function createBody(form: ConnectionForm) {
  return {
    name: form.name.trim(),
    host: form.host.trim(),
    port: Number(form.port),
    database: form.database.trim(),
    username: form.username.trim(),
    password: form.password,
    ssl_mode: form.ssl_mode,
    share_results_with_ai: form.share_results_with_ai,
  };
}

/** "finance, public" -> ["finance", "public"]. Empty means every non-system schema. */
export function parseSchemas(text: string): string[] {
  return [...new Set(text.split(/[,\s]+/).filter(Boolean))];
}

/** The body for having a read-only login made with an admin login that is used once. */
export function provisionBody(form: ConnectionForm, schemas: string) {
  return {
    name: form.name.trim(),
    host: form.host.trim(),
    port: Number(form.port),
    database: form.database.trim(),
    admin_username: form.username.trim(),
    admin_password: form.password,
    ssl_mode: form.ssl_mode,
    share_results_with_ai: form.share_results_with_ai,
    schemas: parseSchemas(schemas),
  };
}

/** Only what changed. The password is left out when the field was left empty (keep it). */
export function changesOf(form: ConnectionForm, connection: Connection) {
  const before = formFromConnection(connection);
  const body: Record<string, unknown> = {};
  if (form.name.trim() !== before.name) body.name = form.name.trim();
  if (form.host.trim() !== before.host) body.host = form.host.trim();
  if (form.port !== before.port) body.port = Number(form.port);
  if (form.database.trim() !== before.database) body.database = form.database.trim();
  if (form.username.trim() !== before.username) body.username = form.username.trim();
  if (form.ssl_mode !== before.ssl_mode) body.ssl_mode = form.ssl_mode;
  if (form.share_results_with_ai !== before.share_results_with_ai) {
    body.share_results_with_ai = form.share_results_with_ai;
  }
  if (form.password) body.password = form.password;
  return body;
}

const ACTIONS: Record<string, string> = {
  "connection.created": "created the connection",
  "connection.updated": "changed the connection",
  "connection.deleted": "deleted the connection",
  "connection.tested": "tested the connection",
  "connection.provisioned": "made a read-only login for the connection",
  "connection.made_read_only": "switched the connection to a read-only login",
  "space.tables_attached": "added tables to the space",
  "space.tables_refreshed": "refreshed the tables of the space",
};

/** One readable line for an audit event, without ever showing a secret. */
export function describeEvent(event: AuditEvent): string {
  const what = ACTIONS[event.action] ?? event.action;
  const detail = event.detail;
  const parts: string[] = [];
  if (Array.isArray(detail.changed) && detail.changed.length > 0) {
    parts.push(`changed: ${detail.changed.join(", ")}`);
  }
  if (Array.isArray(detail.tables) && detail.tables.length > 0) {
    parts.push(detail.tables.join(", "));
  }
  if (typeof detail.status === "string") parts.push(`result: ${detail.status}`);
  if (typeof detail.login === "string") parts.push(`login: ${detail.login}`);
  const suffix = parts.length > 0 ? ` (${parts.join("; ")})` : "";
  return `${event.actor_name || "Someone"} ${what} "${event.target_name}"${suffix}`;
}
