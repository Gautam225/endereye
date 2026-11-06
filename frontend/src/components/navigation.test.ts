import { describe, expect, it } from "vitest";

import { isAlreadyThere, isCurrent, isPlainClick } from "./navigation";

describe("isAlreadyThere", () => {
  it("is true on the page the entry leads to, so the click can be ignored", () => {
    expect(isAlreadyThere("/reports", "/spaces/abc/reports")).toBe(true);
    expect(isAlreadyThere("/reports", "/spaces/abc/reports/")).toBe(true);
    expect(isAlreadyThere("/dashboards", "/spaces/abc/dashboards")).toBe(true);
    expect(isAlreadyThere("/alerts", "/spaces/abc/alerts")).toBe(true);
    expect(isAlreadyThere("/email", "/email")).toBe(true);
    expect(isAlreadyThere("/spaces", "/spaces")).toBe(true);
    expect(isAlreadyThere("/users", "/users")).toBe(true);
  });

  it("treats the chat door as 'there' on any chat, because it leads back to the last one", () => {
    expect(isAlreadyThere("/chat", "/spaces/abc/chat")).toBe(true);
    expect(isAlreadyThere("/chat", "/spaces/abc/chat/c1")).toBe(true);
    expect(isAlreadyThere("/chat", "/chat")).toBe(true);
  });

  it("is false anywhere else, so a real navigation still happens", () => {
    expect(isAlreadyThere("/reports", "/spaces/abc/dashboards")).toBe(false);
    expect(isAlreadyThere("/reports", "/account")).toBe(false);
    expect(isAlreadyThere("/chat", "/spaces/abc/reports")).toBe(false);
    expect(isAlreadyThere("/email", "/spaces/abc")).toBe(false);
  });

  it("does not trap you inside a space: Spaces still leads to the list", () => {
    expect(isCurrent("/spaces", "/spaces/abc")).toBe(true); // highlighted there...
    expect(isAlreadyThere("/spaces", "/spaces/abc")).toBe(false); // ...but the click goes to the list
    expect(isAlreadyThere("/spaces", "/spaces/abc/dashboards")).toBe(false);
  });
});

describe("isCurrent", () => {
  it("marks the entry a page belongs to", () => {
    expect(isCurrent("/chat", "/spaces/a/chat/b")).toBe(true);
    expect(isCurrent("/reports", "/spaces/a/reports")).toBe(true);
    expect(isCurrent("/spaces", "/spaces/a/reports")).toBe(false);
    expect(isCurrent("/spaces", "/spaces/a/chat")).toBe(false);
    expect(isCurrent("/users", "/users")).toBe(true);
  });
});

describe("isPlainClick", () => {
  const base = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false };
  it("leaves a click with a key held (a new tab) or another button alone", () => {
    expect(isPlainClick(base)).toBe(true);
    expect(isPlainClick({ ...base, ctrlKey: true })).toBe(false);
    expect(isPlainClick({ ...base, metaKey: true })).toBe(false);
    expect(isPlainClick({ ...base, shiftKey: true })).toBe(false);
    expect(isPlainClick({ ...base, button: 1 })).toBe(false);
  });
});
