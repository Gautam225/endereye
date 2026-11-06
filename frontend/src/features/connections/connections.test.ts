import { describe, expect, it } from "vitest";

import {
  changesOf,
  createBody,
  describeEvent,
  emptyForm,
  formFromConnection,
  parseSchemas,
  problemsIn,
  provisionBody,
} from "./connections";
import type { AuditEvent, Connection } from "./types";

const saved: Connection = {
  id: "1",
  name: "Warehouse",
  engine: "postgresql",
  host: "db.example.com",
  port: 5432,
  database: "sales",
  username: "reader",
  ssl_mode: "verify-full",
  share_results_with_ai: false,
  status: "ok",
  status_detail: "",
  server_version: "16.2",
  tested_at: null,
  created_at: "2026-01-01T00:00:00Z",
  has_password: true,
};

const valid = {
  ...emptyForm(),
  name: "W",
  host: "db.example.com",
  database: "sales",
  username: "reader",
  password: "x",
};

describe("problemsIn", () => {
  it("accepts a complete form", () => {
    expect(problemsIn(valid, false)).toEqual({});
  });

  it("refuses what the server refuses in a host", () => {
    for (const host of [
      "http://db.example.com",
      "user@db.example.com",
      "db.example.com/x",
      "a b",
      "",
    ]) {
      expect(problemsIn({ ...valid, host }, false).host).toBeTruthy();
    }
    for (const host of ["db.example.com", "10.0.0.5", "localhost", "::1"]) {
      expect(problemsIn({ ...valid, host }, false).host).toBeUndefined();
    }
  });

  it("checks the port and the names", () => {
    expect(problemsIn({ ...valid, port: "0" }, false).port).toBeTruthy();
    expect(problemsIn({ ...valid, port: "70000" }, false).port).toBeTruthy();
    expect(problemsIn({ ...valid, port: "abc" }, false).port).toBeTruthy();
    expect(problemsIn({ ...valid, database: "my db" }, false).database).toBeTruthy();
    expect(problemsIn({ ...valid, username: "" }, false).username).toBeTruthy();
    expect(problemsIn({ ...valid, name: "  " }, false).name).toBeTruthy();
  });

  it("needs a password when creating, not when editing", () => {
    expect(problemsIn({ ...valid, password: "" }, false).password).toBeTruthy();
    expect(problemsIn({ ...valid, password: "" }, true).password).toBeUndefined();
  });
});

describe("request bodies", () => {
  it("builds a new connection with trimmed values and a numeric port", () => {
    expect(createBody({ ...valid, name: " W ", port: "5433" })).toMatchObject({
      name: "W",
      port: 5433,
      password: "x",
      share_results_with_ai: false,
    });
  });

  it("sends only what changed, and keeps the saved password when none was typed", () => {
    const form = formFromConnection(saved);
    expect(changesOf(form, saved)).toEqual({});
    expect(changesOf({ ...form, port: "6543", share_results_with_ai: true }, saved)).toEqual({
      port: 6543,
      share_results_with_ai: true,
    });
    expect(changesOf({ ...form, password: "new-secret" }, saved)).toEqual({
      password: "new-secret",
    });
  });
});

describe("describeEvent", () => {
  const event = (action: string, detail: Record<string, unknown>): AuditEvent => ({
    id: "e",
    created_at: "2026-01-01T00:00:00Z",
    actor_name: "Asha",
    action,
    target_type: "connection",
    target_id: "1",
    target_name: "Warehouse",
    detail,
    ip: null,
  });

  it("writes a plain sentence", () => {
    expect(describeEvent(event("connection.created", {}))).toBe(
      'Asha created the connection "Warehouse"',
    );
    expect(describeEvent(event("connection.updated", { changed: ["password", "name"] }))).toBe(
      'Asha changed the connection "Warehouse" (changed: password, name)',
    );
    expect(describeEvent(event("space.tables_attached", { tables: ["public.orders"] }))).toContain(
      "public.orders",
    );
  });

  it("falls back to the action name for one it does not know", () => {
    expect(describeEvent(event("something.new", {}))).toContain("something.new");
  });
});

describe("provisioning a read-only login", () => {
  it("reads the schemas typed, in any separator, without repeats", () => {
    expect(parseSchemas("")).toEqual([]);
    expect(parseSchemas(" finance, public  finance ")).toEqual(["finance", "public"]);
  });

  it("sends the admin login as admin_*, trimmed, and never as the connection's own login", () => {
    const body = provisionBody(
      { ...valid, name: " W ", username: " postgres ", password: "secret", port: "5433" },
      "finance",
    );

    expect(body).toMatchObject({
      name: "W",
      admin_username: "postgres",
      admin_password: "secret",
      port: 5433,
      schemas: ["finance"],
    });
    expect(body).not.toHaveProperty("username");
    expect(body).not.toHaveProperty("password");
  });
});

describe("describeEvent for logins that were made", () => {
  it("names the new login but never a password", () => {
    const line = describeEvent({
      id: "e",
      created_at: "2026-01-01T00:00:00Z",
      actor_name: "Asha",
      action: "connection.provisioned",
      target_type: "connection",
      target_id: "1",
      target_name: "Warehouse",
      detail: { login: "eoe_reader_1a2b3c4d", tables: 8 },
      ip: null,
    });

    expect(line).toBe(
      'Asha made a read-only login for the connection "Warehouse" (login: eoe_reader_1a2b3c4d)',
    );
  });
});
