import type { Tone } from "../../components/ui/Status";
import type { MessageStatus } from "./types";

export const STATUS_TONE: Record<MessageStatus, Tone> = {
  ok: "ok",
  empty: "neutral",
  answer: "ok",
  clarify: "neutral",
  declined: "warn",
  failed: "error",
  cancelled: "neutral",
  running: "accent",
};

export const STATUS_LABEL: Record<MessageStatus, string> = {
  ok: "Answered",
  empty: "No rows",
  answer: "From documents",
  clarify: "Asked back",
  declined: "Declined",
  failed: "Failed",
  cancelled: "Stopped",
  running: "Running",
};
