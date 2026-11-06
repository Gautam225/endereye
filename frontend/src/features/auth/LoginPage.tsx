import { useQuery } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router";

import { Button } from "../../components/ui/Button";
import { PasswordField, TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { ApiError, publicSend } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { AuthLayout } from "./AuthLayout";
import { FullScreenLoading } from "./guards";
import { StartupProblem } from "./StartupProblem";

interface SsoStatus {
  enabled: boolean;
  name: string;
  password_login: boolean;
}

/** Why a company sign-in did not finish, in words for the person it happened to. */
const SSO_PROBLEMS: Record<string, string> = {
  denied: "Sign-in was cancelled. You can try again.",
  expired: "That sign-in took too long or was opened twice. Please try again.",
  rejected: "Your company sign-in did not accept the request. Please try again.",
  invalid_token: "Your company sign-in sent something we could not verify. Please try again.",
  no_email: "Your company account has no verified email address, so we can't match you.",
  domain_not_allowed: "Your email address is not allowed to use this app. Ask your admin.",
  no_account: "You don't have an account here yet. Ask your admin to add you.",
  account_disabled: "Your account is turned off. Ask an admin to turn it back on.",
  provider_unreachable: "We could not reach your company sign-in. Try again in a moment.",
  provider_misconfigured: "Single sign-on is not set up correctly. Please tell your admin.",
  not_enabled: "Single sign-on is not turned on.",
};

export function LoginPage() {
  const { state, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [params] = useSearchParams();
  const ssoProblem = params.get("sso_error");

  const sso = useQuery({
    queryKey: ["auth", "sso"],
    queryFn: () => publicSend<SsoStatus>("GET", "/auth/sso"),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const single = sso.data?.enabled ? sso.data : null;
  const showForm = !single || single.password_login;

  if (state.status === "loading") return <FullScreenLoading />;
  if (state.status === "error") return <StartupProblem error={state.error} />;
  if (state.status === "authenticated") return <Navigate to={from} replace />;
  if (state.status === "setup") return <Navigate to="/setup" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("Something went wrong.", { code: "error", status: 0 }),
      );
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  function goToCompany() {
    setLeaving(true);
    window.location.assign(`/api/v1/auth/sso/start?next=${encodeURIComponent(from)}`);
  }

  const ended = state.status === "anonymous" && state.reason === "expired";

  return (
    <AuthLayout
      showcase
      title="Welcome back"
      description="Sign in to ask questions about your data."
      footer={<>No account yet? Ask your admin to invite you.</>}
    >
      <div className="space-y-4">
        {ended && !error && !ssoProblem && (
          <Notice title="Your session ended">Please sign in again to continue.</Notice>
        )}
        {ssoProblem && !error && (
          <Notice tone="error" title="Could not sign you in">
            {SSO_PROBLEMS[ssoProblem] ?? "Something went wrong with the company sign-in."}
          </Notice>
        )}
        {error && (
          <Notice tone="error" title={errorTitle(error)}>
            {error.code === "invalid_credentials" ? "Check both and try again." : error.message}
          </Notice>
        )}

        {sso.isPending ? (
          <Skeleton className="h-10" />
        ) : (
          single && (
            <Button
              variant={showForm ? "secondary" : "primary"}
              className="h-10 w-full"
              loading={leaving}
              onClick={goToCompany}
            >
              <KeyRound aria-hidden />
              Continue with {single.name}
            </Button>
          )
        )}

        {single && showForm && (
          <div className="flex items-center gap-3 text-[12.5px] text-subtle" aria-hidden>
            <span className="h-px flex-1 bg-border" />
            or use your email
            <span className="h-px flex-1 bg-border" />
          </div>
        )}

        {showForm && (
          <form onSubmit={submit} className="space-y-4" noValidate>
            <TextField
              label="Email"
              type="email"
              autoComplete="username"
              autoFocus
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <PasswordField
              label="Password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <div className="-mt-2 text-right text-[13px]">
              <Link to="/forgot" className="text-accent underline-offset-4 hover:underline">
                Forgot password?
              </Link>
            </div>
            <Button
              type="submit"
              variant="primary"
              className="h-10 w-full"
              loading={busy}
              disabled={!email.trim() || !password}
            >
              Sign in
            </Button>
          </form>
        )}
      </div>
    </AuthLayout>
  );
}

function errorTitle(error: ApiError): string {
  switch (error.code) {
    case "invalid_credentials":
      return "Wrong email or password";
    case "too_many_requests":
      return "Too many attempts";
    case "account_disabled":
      return "Account turned off";
    case "password_login_disabled":
      return "Use your company sign-in";
    case "validation_error":
      return "Check your email address";
    case "backend_unreachable":
      return "The backend is offline";
    case "database_unavailable":
      return "Can't connect to the database";
    case "database_not_ready":
      return "The database tables need updating";
    default:
      return "Could not sign in";
  }
}
