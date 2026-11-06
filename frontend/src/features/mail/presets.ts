import type { MailSettings } from "./queries";

export interface Preset {
  id: string;
  label: string;
  host: string;
  port: number;
  security: MailSettings["security"];
  /** One line for the choice card. */
  summary: string;
  /** What to know before filling in the rest. */
  help: string;
}

export const PRESETS: Preset[] = [
  {
    id: "gmail",
    label: "Gmail",
    summary: "A personal or Google Workspace address.",
    host: "smtp.gmail.com",
    port: 587,
    security: "starttls",
    help: "Use your Gmail address as the username and an app password, not your normal password. Turn on 2-Step Verification, then make one at myaccount.google.com/apppasswords.",
  },
  {
    id: "outlook",
    label: "Outlook / Microsoft 365",
    summary: "Outlook, Hotmail or a work Microsoft account.",
    host: "smtp.office365.com",
    port: 587,
    security: "starttls",
    help: "Use your full email address as the username. Your administrator must allow SMTP AUTH for the mailbox.",
  },
  {
    id: "other",
    label: "Another service",
    summary: "Any other mail provider or your IT team's server.",
    host: "",
    port: 587,
    security: "starttls",
    help: "Use the details your mail provider or IT team gives you. Port 587 usually means STARTTLS, and 465 means SSL.",
  },
];

/** Which preset the saved host belongs to, so the form opens on it. */
export function presetFor(host: string): Preset {
  return PRESETS.find((p) => p.host !== "" && p.host === host) ?? PRESETS[PRESETS.length - 1]!;
}
