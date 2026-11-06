import { useQuery } from "@tanstack/react-query";
import { MailCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { Button } from "../../components/ui/Button";
import { PasswordField, TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { ApiError, asApiError, publicSend, type Role } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { ROLE_LABEL } from "../users/roles";
import { AuthLayout } from "./AuthLayout";
import { MIN_PASSWORD, PASSWORD_HINT } from "./rules";

interface LinkPreview {
  kind: "invite" | "reset";
  email: string;
  role: Role | null;
  full_name: string | null;
}

const backToSignIn = (
  <Link to="/login" className="text-accent underline-offset-4 hover:underline">
    Back to sign in
  </Link>
);

function useLink(token: string) {
  return useQuery({
    queryKey: ["auth", "link", token],
    queryFn: () => publicSend<LinkPreview>("GET", `/auth/links/${encodeURIComponent(token)}`),
    retry: false,
    staleTime: Infinity, // looked at once: the link is used up by the form below
  });
}

/** A link that cannot be used: it expired, was used already, or was replaced by a newer one. */
function DeadLink({ kind }: { kind: "invite" | "reset" }) {
  return (
    <AuthLayout
      showcase
      title="This link no longer works"
      description={
        kind === "reset"
          ? "Reset links work once and expire after an hour."
          : "Invitation links work once and expire after a week."
      }
      footer={backToSignIn}
    >
      <Notice tone="warn" title="Ask for a new one">
        {kind === "reset" ? (
          <>
            You can{" "}
            <Link to="/forgot" className="text-accent underline-offset-4 hover:underline">
              request another reset link
            </Link>
            .
          </>
        ) : (
          "Ask the person who invited you to send the invitation again."
        )}
      </Notice>
    </AuthLayout>
  );
}

function Loading() {
  return (
    <AuthLayout showcase title="One moment…">
      <Skeleton className="h-40" />
    </AuthLayout>
  );
}

/** Two password boxes with the same rules as the rest of the app. */
function usePasswordForm() {
  const [form, setForm] = useState({ full_name: "", password: "", confirm: "" });
  const [touched, setTouched] = useState(false);
  const update = (field: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: event.target.value }));
  const problems = {
    full_name: form.full_name.trim() ? undefined : "Enter your name.",
    password:
      form.password.length >= MIN_PASSWORD ? undefined : `Use at least ${MIN_PASSWORD} characters.`,
    confirm: form.confirm === form.password ? undefined : "The passwords don't match.",
  };
  return { form, update, touched, setTouched, problems };
}

// ── Invitation ───────────────────────────────────────────────────────────────

export function InvitePage() {
  const { token = "" } = useParams();
  const link = useLink(token);
  if (link.isPending) return <Loading />;
  if (link.isError || link.data.kind !== "invite") return <DeadLink kind="invite" />;
  return <InviteForm token={token} link={link.data} />;
}

function InviteForm({ token, link }: { token: string; link: LinkPreview }) {
  const { acceptInvite } = useAuth();
  const navigate = useNavigate();
  const { form, update, touched, setTouched, problems } = usePasswordForm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const shown = (field: keyof typeof problems) =>
    (touched ? problems[field] : undefined) ?? error?.fieldErrors[field];

  async function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (Object.values(problems).some(Boolean)) return;
    setBusy(true);
    setError(null);
    try {
      await acceptInvite(token, form.full_name, form.password);
      navigate("/", { replace: true });
    } catch (caught) {
      setError(asApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      showcase
      title="Welcome aboard"
      description={
        <>
          You were invited as {link.role ? ROLE_LABEL[link.role].toLowerCase() : "a member"}. Choose
          a password to finish.
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && error.code !== "validation_error" && (
          <Notice tone="error" title="Could not create your account">
            {error.message}
          </Notice>
        )}
        <TextField label="Email" value={link.email} readOnly disabled />
        <TextField
          label="Your name"
          autoComplete="name"
          autoFocus
          value={form.full_name}
          onChange={update("full_name")}
          error={shown("full_name")}
        />
        <PasswordField
          label="Choose a password"
          autoComplete="new-password"
          value={form.password}
          onChange={update("password")}
          error={shown("password")}
          hint={PASSWORD_HINT}
        />
        <PasswordField
          label="Confirm password"
          autoComplete="new-password"
          value={form.confirm}
          onChange={update("confirm")}
          error={shown("confirm")}
        />
        <Button type="submit" variant="primary" className="h-10 w-full" loading={busy}>
          Create my account
        </Button>
      </form>
    </AuthLayout>
  );
}

// ── Forgot password ──────────────────────────────────────────────────────────

export function ForgotPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await publicSend("POST", "/auth/forgot", { email: email.trim() });
      setSent(true);
    } catch (caught) {
      setError(asApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <AuthLayout showcase title="Check your email" footer={backToSignIn}>
        <div className="space-y-4">
          <span className="flex size-11 items-center justify-center rounded-full bg-accent-soft text-accent">
            <MailCheck aria-hidden className="size-5" />
          </span>
          <p className="text-[15px] text-muted">
            If <b className="font-medium text-fg">{email.trim()}</b> has an account, we sent a link
            to choose a new password. It works once and expires in an hour.
          </p>
          <p className="text-[13px] text-subtle">
            Nothing arrived? Look in your spam folder, or ask your admin: email may not be set up
            yet.
          </p>
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      showcase
      title="Forgot your password?"
      description="Enter your email and we will send you a link to choose a new one."
      footer={backToSignIn}
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && (
          <Notice tone="error" title="Could not send the link">
            {error.message}
          </Notice>
        )}
        <TextField
          label="Email"
          type="email"
          autoComplete="username"
          autoFocus
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Button
          type="submit"
          variant="primary"
          className="h-10 w-full"
          loading={busy}
          disabled={!/\S+@\S+\.\S+/.test(email)}
        >
          Send me a link
        </Button>
      </form>
    </AuthLayout>
  );
}

// ── Choosing a new password ──────────────────────────────────────────────────

export function ResetPage() {
  const { token = "" } = useParams();
  const link = useLink(token);
  if (link.isPending) return <Loading />;
  if (link.isError || link.data.kind !== "reset") return <DeadLink kind="reset" />;
  return <ResetForm token={token} link={link.data} />;
}

function ResetForm({ token, link }: { token: string; link: LinkPreview }) {
  const { resetPassword } = useAuth();
  const navigate = useNavigate();
  const { form, update, touched, setTouched, problems } = usePasswordForm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const shown = (field: "password" | "confirm") =>
    (touched ? problems[field] : undefined) ?? error?.fieldErrors[field];

  async function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (problems.password || problems.confirm) return;
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, form.password);
      navigate("/", { replace: true });
    } catch (caught) {
      setError(asApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      showcase
      title="Choose a new password"
      description={
        <>
          For <b className="font-medium text-fg">{link.email}</b>. You will be signed out everywhere
          else.
        </>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && error.code !== "validation_error" && (
          <Notice tone="error" title="Could not change the password">
            {error.message}
          </Notice>
        )}
        <PasswordField
          label="New password"
          autoComplete="new-password"
          autoFocus
          value={form.password}
          onChange={update("password")}
          error={shown("password")}
          hint={PASSWORD_HINT}
        />
        <PasswordField
          label="Confirm password"
          autoComplete="new-password"
          value={form.confirm}
          onChange={update("confirm")}
          error={shown("confirm")}
        />
        <Button type="submit" variant="primary" className="h-10 w-full" loading={busy}>
          Save and sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
