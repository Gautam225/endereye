const CHAT = /^\/chat(\/|$)|^\/spaces\/[^/]+\/chat(\/|$)/;
const SPACE_SECTION = /^\/spaces\/[^/]+\/(dashboards|reports|alerts)(\/|$)/;

/** Which menu entry the current page belongs to. Chat lives under /spaces too, so it is checked first. */
export function isCurrent(to: string, pathname: string): boolean {
  const chat = CHAT.test(pathname);
  if (to === "/chat") return chat;
  const kept = SPACE_SECTION.exec(pathname)?.[1];
  if (to === "/dashboards") return pathname === to || kept === "dashboards";
  if (to === "/reports") return pathname === to || kept === "reports";
  if (to === "/alerts") return pathname === to || kept === "alerts";
  if (to === "/spaces") return pathname.startsWith("/spaces") && !chat && !kept;
  return pathname === to || pathname.startsWith(`${to}/`);
}

/**
 * Would a click on this menu entry only bring you back to the page you are already on?
 *
 * If so the click should do nothing: following it would reload the page (and ask the server for
 * everything again) to arrive exactly where you are. A few entries are doors that lead to your
 * last space or chat (`/reports`, `/chat`); they are "already there" when you are on that kind
 * of page, because the door would lead straight back to it.
 *
 * It is narrower than `isCurrent`: "Spaces" is the current entry inside a space, but clicking it
 * there must still go to the list of spaces.
 */
export function isAlreadyThere(to: string, pathname: string): boolean {
  if (to === "/chat") return CHAT.test(pathname);
  if (to === "/dashboards" || to === "/reports" || to === "/alerts") {
    const section = to.slice(1);
    return pathname === to || new RegExp(`^/spaces/[^/]+/${section}/?$`).test(pathname);
  }
  return pathname.replace(/\/+$/, "") === to;
}

/** A plain left click, with no key held: the kind that follows a link in this window. */
export function isPlainClick(event: {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}
