import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";

import { Button } from "../../components/ui/Button";
import { PasswordField, TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { AuthLayout } from "./AuthLayout";
import { FullScreenLoading } from "./guards";
import { MIN_PASSWORD, PASSWORD_HINT } from "./rules";

export function SetupPage() {
  const { state, setup } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", password: "", confirm: "" });
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  if (state.status === "loading") return <FullScreenLoading />;
  if (state.status !== "setup") return <Navigate to="/" replace />;

  const problems = {
    full_name: form.full_name.trim() ? undefined : "Enter your name.",
    email: /\S+@\S+\.\S+/.test(form.email) ? undefined : "Enter a valid email address.",
    password:
      form.password.length >= MIN_PASSWORD ? undefined : `Use at least ${MIN_PASSWORD} characters.`,
    confirm: form.confirm === form.password ? undefined : "The passwords don't match.",
  };
  const server = error?.fieldErrors ?? {};
  const shown = (field: keyof typeof problems) =>
    (touched ? problems[field] : undefined) ?? server[field];

  async function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (Object.values(problems).some(Boolean)) return;
    setBusy(true);
    setError(null);
    try {
      await setup({ full_name: form.full_name, email: form.email, password: form.password });
      navigate("/", { replace: true });
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError("Something went wrong.", { code: "error", status: 0 }),
      );
    } finally {
      setBusy(false);
    }
  }

  const update = (field: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: event.target.value }));

  return (
    <AuthLayout
      showcase
      title="Create the admin account"
      description="This is the first account, so it becomes the admin. You can add everyone else later from Users."
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        {error && error.code !== "validation_error" && (
          <Notice tone="error" title="Could not create the account">
            {error.message}
          </Notice>
        )}
        <TextField
          label="Full name"
          autoComplete="name"
          autoFocus
          value={form.full_name}
          onChange={update("full_name")}
          error={shown("full_name")}
        />
        <TextField
          label="Email"
          type="email"
          autoComplete="username"
          value={form.email}
          onChange={update("email")}
          error={shown("email")}
        />
        <PasswordField
          label="Password"
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
        <Button type="submit" variant="primary" className="w-full" loading={busy}>
          Create account and sign in
        </Button>
      </form>
    </AuthLayout>
  );
}
