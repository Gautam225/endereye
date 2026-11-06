import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { forgetChat, lastChat, rememberChat } from "./lastSpace";

/** A stand-in for the browser's storage, since the tests run without a browser. */
function fakeStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  };
}

describe("the chat you were last in", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", fakeStorage());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("remembers the space and the conversation", () => {
    rememberChat("ann", "space-1", "chat-9");
    expect(lastChat("ann")).toEqual({ spaceId: "space-1", conversationId: "chat-9" });
  });

  it("remembers a space where no conversation is open yet", () => {
    rememberChat("ann", "space-1", null);
    expect(lastChat("ann")).toEqual({ spaceId: "space-1", conversationId: null });
  });

  it("keeps each person's chat to themselves and follows the latest one", () => {
    rememberChat("ann", "space-1", "chat-1");
    rememberChat("bob", "space-2", "chat-2");
    rememberChat("ann", "space-3", "chat-3");
    expect(lastChat("ann")).toEqual({ spaceId: "space-3", conversationId: "chat-3" });
    expect(lastChat("bob")).toEqual({ spaceId: "space-2", conversationId: "chat-2" });
    expect(lastChat("cy")).toBeNull();
  });

  it("forgets one that is gone", () => {
    rememberChat("ann", "space-1", "chat-1");
    forgetChat("ann");
    expect(lastChat("ann")).toBeNull();
  });

  it("ignores anything stored that is not a chat", () => {
    localStorage.setItem("eoe.chat.last.ann", "not json");
    expect(lastChat("ann")).toBeNull();
    localStorage.setItem("eoe.chat.last.ann", JSON.stringify({ spaceId: 5 }));
    expect(lastChat("ann")).toBeNull();
    localStorage.setItem("eoe.chat.last.ann", JSON.stringify({ spaceId: "" }));
    expect(lastChat("ann")).toBeNull();
  });
});
