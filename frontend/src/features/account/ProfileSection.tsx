import { Lock } from "lucide-react";

import { Badge } from "../../components/ui/Status";
import { useAuth } from "../../lib/auth";
import { timeAgo } from "../../lib/format";
import { ROLE_LABEL } from "../users/roles";
import { SettingRow, SettingsSection } from "./SettingsSection";

/** Who you are here. It is read-only: an administrator manages names and emails. */
export function ProfileSection() {
  const { user } = useAuth();
  if (!user) return null;
  const joined = new Date(user.created_at).toLocaleDateString(undefined, { dateStyle: "long" });

  return (
    <SettingsSection
      id="profile"
      title="Profile"
      description="How you appear to the people you work with."
      footer={
        <span className="inline-flex items-center gap-1.5">
          <Lock aria-hidden className="size-3" />
          Your name and email are managed by an administrator.
        </span>
      }
    >
      <SettingRow title="Name">
        <span className="text-[14px]">{user.full_name}</span>
      </SettingRow>
      <SettingRow title="Email">
        <span className="text-[14px] break-all">{user.email}</span>
      </SettingRow>
      <SettingRow title="Role" description="What you are allowed to do across the app.">
        <Badge tone={user.role === "admin" ? "accent" : "neutral"}>{ROLE_LABEL[user.role]}</Badge>
      </SettingRow>
      <SettingRow title="Member since">
        <span className="text-[14px]">{joined}</span>
      </SettingRow>
      <SettingRow title="Last sign-in">
        <span className="text-[14px]">{timeAgo(user.last_login_at)}</span>
      </SettingRow>
    </SettingsSection>
  );
}
