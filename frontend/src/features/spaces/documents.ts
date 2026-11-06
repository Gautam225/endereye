import type { DocumentInfo } from "./types";

/**
 * A saved document is read and indexed on the server after the upload ends. While any is still
 * `processing`, ask again every so often (a refresh in the meantime loses nothing).
 */
export function documentsPollInterval(
  documents: Pick<DocumentInfo, "status">[] | undefined,
): number | false {
  return documents?.some((d) => d.status === "processing") ? 1500 : false;
}
