import { DEFAULT_DURATION, type ToastInput, type ToastLevel } from "../../lib/toast";

/** What the server hands over: something that happened, for this person. */
export interface ServerNotification {
  id: string;
  kind: string;
  level: ToastLevel;
  title: string;
  body: string;
  /** A page of the app, with its query: "/spaces/1/reports?report=2". */
  link: string;
  action: ServerAction | null;
  /** Not shown while the person is already looking at `link`. */
  quiet_when_here: boolean;
  created_at: string;
}

export interface ServerAction {
  type: "download";
  label: string;
  path: string;
  filename: string;
}

/** The path of a link, without its query or fragment. */
export function pathOf(link: string): string {
  return link.split(/[?#]/)[0] ?? "";
}

/** Is the person already on the page this notification points to? */
export function isHere(pathname: string, link: string): boolean {
  if (link === "") return false;
  return pathname.replace(/\/+$/, "") === pathOf(link).replace(/\/+$/, "");
}

/** Extra time for a toast that has a button, so there is time to reach it. */
const WITH_ACTION_MS = 10_000;

/**
 * A notification as a toast. `perform` carries out the button (the server only names what it
 * is), so this stays free of network code.
 */
export function toastFromNotification(
  note: ServerNotification,
  perform: (action: ServerAction) => void | Promise<void>,
): ToastInput {
  const action = note.action;
  const duration = DEFAULT_DURATION[note.level];
  return {
    id: note.id,
    title: note.title,
    body: note.body,
    level: note.level,
    link: note.link,
    action: action ? { label: action.label, onClick: () => perform(action) } : undefined,
    duration: duration !== null && action ? WITH_ACTION_MS : duration,
  };
}
