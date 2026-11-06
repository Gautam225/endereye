import { LoaderCircle, ShieldOff } from "lucide-react";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { PageHeader } from "../../components/PageHeader";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/Notice";
import type { Role } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { StartupProblem } from "./StartupProblem";

export function FullScreenLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center text-muted" role="status">
      <LoaderCircle aria-hidden className="mr-2 size-4 animate-spin" />
      Loading…
    </div>
  );
}

/** Shows its children only to signed-in users; everyone else goes to sign-in or setup. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const location = useLocation();

  switch (state.status) {
    case "loading":
      return <FullScreenLoading />;
    case "setup":
      return <Navigate to="/setup" replace />;
    case "anonymous":
      // Come back here after signing in, except after a deliberate sign-out: the next
      // person to sign in should start fresh, not on the previous person's page.
      return (
        <Navigate
          to="/login"
          replace
          state={state.reason === "signed_out" ? undefined : { from: location.pathname }}
        />
      );
    case "error":
      return <StartupProblem error={state.error} />;
    case "authenticated":
      return children;
  }
}

/** Shows its children only to the given roles; others see a clear "no access" page. */
export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { hasRole } = useAuth();
  if (hasRole(...roles)) return children;
  return (
    <>
      <PageHeader title="No access" />
      <Card>
        <EmptyState icon={ShieldOff} title="This page is for admins">
          Ask an admin if you need access.
        </EmptyState>
      </Card>
    </>
  );
}

/** The first page after sign-in: asking questions for viewers, the spaces for everyone else. */
export function HomeRedirect() {
  const { hasRole } = useAuth();
  return <Navigate to={hasRole("viewer") ? "/chat" : "/spaces"} replace />;
}
