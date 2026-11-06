import type { Role } from "../../lib/api";

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  editor: "Editor",
  viewer: "Viewer",
};

export const ROLE_HELP: Record<Role, string> = {
  admin: "Everything, including users and system tools",
  editor: "Sets up spaces: data, instructions, examples",
  viewer: "Asks questions",
};

export const ROLE_OPTIONS = (Object.keys(ROLE_LABEL) as Role[]).map((role) => ({
  value: role,
  label: ROLE_LABEL[role],
}));
