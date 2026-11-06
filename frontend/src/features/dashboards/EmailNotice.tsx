import type { ReactNode } from "react";
import { Link } from "react-router";

import { Notice } from "../../components/ui/Notice";
import { useAuth } from "../../lib/auth";

/** Shown while no mail account is set up: says what still works, and who can fix it. */
export function EmailNotice({ children }: { children: ReactNode }) {
  const { hasRole } = useAuth();
  return (
    <Notice tone="warn" title="Email is not set up yet">
      {children}{" "}
      {hasRole("admin") ? (
        <>
          You can set it up now on the{" "}
          <Link to="/email" className="font-medium text-accent underline-offset-2 hover:underline">
            Email page
          </Link>
          .
        </>
      ) : (
        "Ask an administrator to set up email."
      )}
    </Notice>
  );
}
