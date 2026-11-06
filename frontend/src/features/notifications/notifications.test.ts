import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "../../lib/api";
import { isHere, pathOf, toastFromNotification, type ServerNotification } from "./mapping";
import {
  applyChange,
  isCategoryMuted,
  isQuiet,
  pauseEnds,
  pausedUntilText,
  type Preferences,
} from "./preferences";
import { toastMutationError, toastServerBack, toastServerDown } from "./globalToasts";
import { MAX_VISIBLE, getToasts, resetToasts, split, toast } from "../../lib/toast";

const all = getToasts;

describe("toast", () => {
  beforeEach(resetToasts);

  it("keeps good news short and lets problems stay until they are closed", () => {
    toast.success("Saved");
    toast.info("FYI");
    toast.warning("Careful");
    toast.error("Broke");

    const [saved, info, warning, error] = all();
    expect(saved?.duration).toBe(6000);
    expect(info?.duration).toBe(6000);
    expect(warning?.duration).toBeNull();
    expect(error?.duration).toBeNull();
  });

  it("lets the caller choose how long, or keep it", () => {
    toast.success("Quick", { duration: 1500 });
    toast.success("Stays", { duration: null });
    expect(all().map((t) => t.duration)).toEqual([1500, null]);
  });

  it("replaces a toast that has the same id instead of stacking another", () => {
    toast.warning("Offline", { id: "offline" });
    const before = all()[0]!;
    toast.warning("Still offline", { id: "offline", body: "Trying again" });

    const now = all();
    expect(now).toHaveLength(1);
    expect(now[0]).toMatchObject({ title: "Still offline", body: "Trying again" });
    expect(now[0]!.shown).not.toBe(before.shown); // its timer starts over
  });

  it("dismisses one, ignores one that is gone, and clears all", () => {
    const a = toast.info("A");
    toast.info("B");
    toast.dismiss(a);
    toast.dismiss("nope");
    expect(all().map((t) => t.title)).toEqual(["B"]);
    toast.clear();
    expect(all()).toEqual([]);
  });

  it("shows the first few and keeps the rest waiting, oldest first", () => {
    for (const n of [1, 2, 3, 4, 5]) toast.info(`T${n}`);
    const { visible, waiting } = split(all());
    expect(visible.map((t) => t.title)).toEqual(["T1", "T2", "T3"]);
    expect(waiting).toBe(5 - MAX_VISIBLE);

    toast.dismiss(visible[0]!.id);
    expect(split(all()).visible.map((t) => t.title)).toEqual(["T2", "T3", "T4"]);
  });

  it("remembers the page and the button a toast carries", () => {
    toast.success("Ready", {
      link: "/reports",
      action: { label: "Download", onClick: () => undefined },
    });
    expect(all()[0]).toMatchObject({ link: "/reports", action: { label: "Download" } });
  });
});

const note = (over: Partial<ServerNotification> = {}): ServerNotification => ({
  id: "n1",
  kind: "report_ready",
  level: "success",
  title: "Weekly is ready",
  body: "Sent to 2 people.",
  link: "/spaces/1/reports?report=9",
  action: null,
  quiet_when_here: false,
  created_at: "2026-11-18T10:00:00Z",
  ...over,
});

describe("toastFromNotification", () => {
  it("turns a notification into a toast with its page, and problems stay", () => {
    const ready = toastFromNotification(note(), () => undefined);
    expect(ready).toMatchObject({
      id: "n1",
      title: "Weekly is ready",
      level: "success",
      link: "/spaces/1/reports?report=9",
      duration: 6000,
    });
    const failed = toastFromNotification(note({ level: "error" }), () => undefined);
    expect(failed.duration).toBeNull();
  });

  it("gives a toast with a button more time, and the button does what the server named", () => {
    const done: string[] = [];
    const download = {
      type: "download" as const,
      label: "Download PDF",
      path: "/x",
      filename: "a.pdf",
    };
    const input = toastFromNotification(note({ action: download }), (a) => void done.push(a.path));

    expect(input.duration).toBe(10_000);
    expect(input.action?.label).toBe("Download PDF");
    void input.action?.onClick();
    expect(done).toEqual(["/x"]);
  });
});

describe("where the person is", () => {
  it("compares the page, not the query", () => {
    expect(pathOf("/spaces/1/chat/2?x=1#top")).toBe("/spaces/1/chat/2");
    expect(isHere("/spaces/1/chat/2", "/spaces/1/chat/2")).toBe(true);
    expect(isHere("/spaces/1/chat/2/", "/spaces/1/chat/2?x=1")).toBe(true);
    expect(isHere("/spaces/1/chat/3", "/spaces/1/chat/2")).toBe(false);
    expect(isHere("/spaces/1/chat", "")).toBe(false);
  });
});

describe("toasts for failed actions and a missing server", () => {
  beforeEach(resetToasts);

  it("says an action failed only when the action asked for a toast, with the server's reason", () => {
    const problem = new ApiError("That file is too large.", { code: "too_large", status: 413 });

    toastMutationError(problem, undefined);
    toastMutationError(problem, {});
    expect(getToasts()).toEqual([]);

    toastMutationError(problem, { errorToast: "Upload failed" });
    expect(getToasts()).toHaveLength(1);
    expect(getToasts()[0]).toMatchObject({
      title: "Upload failed",
      body: "That file is too large.",
      level: "error",
      duration: null,
    });
  });

  it("does not repeat the same failure, and leaves a missing server to its own toast", () => {
    const problem = new ApiError("Nope.", { code: "bad", status: 400 });
    toastMutationError(problem, { errorToast: "Upload failed" });
    toastMutationError(problem, { errorToast: "Upload failed" });
    expect(getToasts()).toHaveLength(1);

    resetToasts();
    const down = new ApiError("Can't reach the backend.", {
      code: "backend_unreachable",
      status: 0,
    });
    toastMutationError(down, { errorToast: "Upload failed" });
    expect(getToasts()).toEqual([]);
  });

  it("shows one 'can't reach the server' however many requests fail, and says when it is back", () => {
    const down = new ApiError("Can't reach the backend.", {
      code: "backend_unreachable",
      status: 0,
    });
    toastServerDown(down);
    toastServerDown(down);
    toastServerDown(new ApiError("Other", { code: "x", status: 500 }));
    expect(getToasts().map((t) => t.title)).toEqual(["Can't reach the server"]);

    toastServerBack();
    expect(getToasts().map((t) => t.title)).toEqual(["Connected again"]);
    toastServerBack(); // nothing was down any more: nothing to say
    expect(getToasts()).toHaveLength(1);
  });
});

const prefs = (over: Partial<Preferences> = {}): Preferences => ({
  enabled: true,
  paused_until: null,
  categories: [
    {
      id: "reports",
      group: "Your work",
      title: "Reports",
      description: "",
      enabled: true,
      client_only: false,
      admin_only: false,
    },
    {
      id: "connection",
      group: "Access and connection",
      title: "Connection",
      description: "",
      enabled: false,
      client_only: true,
      admin_only: false,
    },
  ],
  ...over,
});

describe("pausing", () => {
  const now = new Date(2026, 10, 18, 14, 20); // 18 Nov, 2:20 PM

  it("ends an hour or four hours from now, or at 8 the next morning", () => {
    expect(pauseEnds("hour", now).getTime()).toBe(now.getTime() + 3_600_000);
    expect(pauseEnds("four-hours", now).getTime()).toBe(now.getTime() + 4 * 3_600_000);
    const morning = pauseEnds("tomorrow", now);
    expect([morning.getDate(), morning.getHours(), morning.getMinutes()]).toEqual([19, 8, 0]);
  });

  it("is quiet when switched off or paused for a time still ahead", () => {
    expect(isQuiet(prefs(), now)).toBe(false);
    expect(isQuiet(prefs({ enabled: false }), now)).toBe(true);
    const ahead = new Date(now.getTime() + 60_000).toISOString();
    const behind = new Date(now.getTime() - 60_000).toISOString();
    expect(isQuiet(prefs({ paused_until: ahead }), now)).toBe(true);
    expect(isQuiet(prefs({ paused_until: behind }), now)).toBe(false);
  });

  it("says when a pause ends in words", () => {
    const later = new Date(2026, 10, 18, 15, 40).toISOString();
    const tomorrow = new Date(2026, 10, 19, 8, 0).toISOString();
    expect(pausedUntilText(later, now)).toMatch(/3:40/);
    expect(pausedUntilText(tomorrow, now)).toMatch(/^tomorrow .*8:00/);
  });
});

describe("what the browser mutes", () => {
  it("mutes a category the person turned off, and everything while quiet", () => {
    expect(isCategoryMuted(prefs(), "connection")).toBe(true);
    expect(isCategoryMuted(prefs(), "reports")).toBe(false);
    expect(isCategoryMuted(prefs({ enabled: false }), "reports")).toBe(true);
    expect(isCategoryMuted(prefs(), "unknown")).toBe(false);
  });

  it("does not show a toast of a muted category, and shows one with no category", () => {
    resetToasts();
    toast.setMuter((category) => category === "connection");
    toast.warning("Offline", { category: "connection" });
    toast.warning("Offline too", { id: "x" });
    toast.setMuter(null);
    expect(getToasts().map((t) => t.title)).toEqual(["Offline too"]);
    resetToasts();
  });
});

describe("applyChange", () => {
  it("shows a change before the server answers, leaving the rest alone", () => {
    const changed = applyChange(prefs(), { categories: { reports: false } });
    expect(changed.categories.map((c) => c.enabled)).toEqual([false, false]);
    expect(changed.enabled).toBe(true);
    const off = applyChange(prefs(), { enabled: false });
    expect(off.enabled).toBe(false);
    const paused = applyChange(prefs(), { paused_until: "2026-11-18T16:00:00Z" });
    expect(paused.paused_until).toBe("2026-11-18T16:00:00Z");
    expect(applyChange(paused, { clear_pause: true }).paused_until).toBeNull();
  });
});
