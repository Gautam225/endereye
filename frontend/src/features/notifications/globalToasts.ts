import { ApiError, asApiError } from "../../lib/api";
import { getToasts, toast } from "../../lib/toast";
import { SERVER_DOWN_ID } from "./useConnectionToasts";

/**
 * A mutation (an upload, a refresh, a run) that failed. A mutation opts in with
 * `meta: { errorToast: "Upload failed" }`: the toast then says that, with the server's reason
 * underneath. Mutations without it keep showing their error where they always did, so nothing
 * is said twice.
 */
export function toastMutationError(
  error: unknown,
  meta: Record<string, unknown> | undefined,
): void {
  const label = meta?.errorToast;
  if (typeof label !== "string" || label === "") return;
  const problem = asApiError(error);
  if (problem.code === "backend_unreachable") return; // said once, as "Can't reach the server"
  toast.error(label, { id: `error:${label}`, body: problem.message });
}

/** The server did not answer at all: one toast, however many requests failed. */
export function toastServerDown(error: unknown): void {
  if (!(error instanceof ApiError) || error.code !== "backend_unreachable") return;
  if (typeof navigator !== "undefined" && navigator.onLine === false) return; // the offline toast covers it
  toast.error("Can't reach the server", {
    id: SERVER_DOWN_ID,
    category: "connection",
    body: "It may be restarting. This page keeps trying and will tell you when it is back.",
  });
}

/** Something worked again: if the person was told the server was down, say it is back. */
export function toastServerBack(): void {
  if (!getToasts().some((t) => t.id === SERVER_DOWN_ID)) return;
  toast.dismiss(SERVER_DOWN_ID);
  toast.success("Connected again", {
    id: "server-back",
    duration: 3500,
    category: "connection",
  });
}
