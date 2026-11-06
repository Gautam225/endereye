import { Bell, Mail, Palette, ShieldCheck, UserRound } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, type ReactNode } from "react";
import { useSearchParams } from "react-router";

import { Badge } from "../../components/ui/Status";
import { useAuth } from "../../lib/auth";
import { initials } from "../../lib/format";
import { isQuiet, usePreferences } from "../notifications/preferences";
import { ROLE_LABEL } from "../users/roles";
import { AppearanceSection } from "./AppearanceSection";
import { EmailSection } from "./EmailSection";
import { NotificationsSection } from "./NotificationsSection";
import { PasswordSection } from "./PasswordSection";
import { ProfileSection } from "./ProfileSection";
import { SettingsNav, type SectionLink } from "./SettingsSection";

type SectionId = "profile" | "notifications" | "email" | "appearance" | "security";

const PAGES: Record<SectionId, { label: string; icon: SectionLink["icon"]; page: ReactNode }> = {
  profile: { label: "Profile", icon: UserRound, page: <ProfileSection /> },
  notifications: { label: "Notifications", icon: Bell, page: <NotificationsSection /> },
  email: { label: "Email", icon: Mail, page: <EmailSection /> },
  appearance: { label: "Appearance", icon: Palette, page: <AppearanceSection /> },
  security: { label: "Security", icon: ShieldCheck, page: <PasswordSection /> },
};

const ORDER: SectionId[] = ["profile", "notifications", "email", "appearance", "security"];

/**
 * Account settings, one page at a time. Showing every setting at once asks people to read it
 * all to find the one they want; a short menu and a single page keep each visit to one decision.
 * The page is named in the address (`?section=notifications`), so a link, a refresh, or the
 * back button all land where you were.
 */
export function AccountPage() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const prefs = usePreferences();
  const requested = params.get("section");
  const active: SectionId = ORDER.find((id) => id === requested) ?? "profile";

  useEffect(() => {
    document.title = `${PAGES[active].label} · Account · Eye of Ender`;
  }, [active]);

  if (!user) return null;

  // A state worth seeing without opening the page: pop-ups are paused or off.
  const quiet = prefs.data ? isQuiet(prefs.data) : false;
  const links: SectionLink[] = ORDER.map((id) => ({
    id,
    label: PAGES[id].label,
    icon: PAGES[id].icon,
    badge: id === "notifications" && quiet ? (prefs.data?.enabled ? "Paused" : "Off") : undefined,
  }));

  return (
    <div className="mx-auto w-full max-w-5xl">
      <header className="mb-8 flex items-center gap-4">
        <span
          aria-hidden
          className="flex size-14 shrink-0 items-center justify-center rounded-full bg-surface-2 text-[18px] font-semibold text-fg ring-1 ring-border"
        >
          {initials(user.full_name)}
        </span>
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-2.5 text-[24px] leading-8 font-semibold tracking-[-0.015em]">
            <span className="truncate">{user.full_name}</span>
            <Badge tone={user.role === "admin" ? "accent" : "neutral"}>
              {ROLE_LABEL[user.role]}
            </Badge>
          </h1>
          <p className="truncate text-[14px] text-muted">{user.email}</p>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-12">
        <SettingsNav links={links} active={active} />
        <div className="min-w-0 lg:max-w-3xl">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={active}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            >
              {PAGES[active].page}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
