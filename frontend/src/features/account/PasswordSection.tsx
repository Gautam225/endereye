import { Check, Circle } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import { PasswordField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/cn";
import { MIN_PASSWORD } from "../auth/rules";
import { passwordStrength } from "./helpers";
import { SettingRow, SettingsSection } from "./SettingsSection";

const BAR = ["bg-border", "bg-danger", "bg-warning", "bg-success", "bg-success"];

export function PasswordSection() {
  const { changePassword } = useAuth();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [done, setDone] = useState(false);
  const [open, setOpen] = useState(false);

  const strength = passwordStrength(form.next);
  const long = form.next.length >= MIN_PASSWORD;
  const matches = form.confirm !== "" && form.confirm === form.next;
  const problems = {
    current: form.current ? undefined : "Enter your current password.",
    next: long ? undefined : `Use at least ${MIN_PASSWORD} characters.`,
    confirm: form.confirm === form.next ? undefined : "The passwords don't match.",
  };
  const shown = (field: keyof typeof problems) => (touched ? problems[field] : undefined);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    setDone(false);
    if (Object.values(problems).some(Boolean)) return;
    setBusy(true);
    setError(null);
    try {
      await changePassword(form.current, form.next);
      setForm({ current: "", next: "", confirm: "" });
      setTouched(false);
      setDone(true);
      setOpen(false);
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
    <SettingsSection
      id="password"
      title="Security"
      description="Keep your account safe with a strong password."
    >
      {!open && (
        <>
          {done && (
            <div className="px-5 py-4">
              <Notice title="Password changed">
                You are still signed in here. Every other device was signed out.
              </Notice>
            </div>
          )}
          <SettingRow
            title="Password"
            description="Use a long password or a short sentence. Changing it signs you out of every other device."
          >
            <Button
              onClick={() => {
                setDone(false);
                setOpen(true);
              }}
            >
              Change password
            </Button>
          </SettingRow>
        </>
      )}
      {open && (
        <form onSubmit={submit} className="space-y-5 p-5" noValidate>
          {error && (
            <Notice tone="error" title="Password not changed">
              {error.message}
            </Notice>
          )}
          <div className="grid max-w-3xl gap-5 md:grid-cols-2">
            <div className="md:col-span-2 md:max-w-[calc(50%-0.625rem)]">
              <PasswordField
                label="Current password"
                autoComplete="current-password"
                value={form.current}
                onChange={update("current")}
                error={shown("current")}
              />
            </div>
            <div className="space-y-2.5">
              <PasswordField
                label="New password"
                autoComplete="new-password"
                value={form.next}
                onChange={update("next")}
                error={shown("next")}
              />
              <div aria-live="polite" className="space-y-1.5">
                <div className="flex gap-1" aria-hidden>
                  {[1, 2, 3, 4].map((step) => (
                    <span
                      key={step}
                      className={cn(
                        "h-1 flex-1 rounded-full transition-colors",
                        strength.level >= step ? BAR[strength.level] : "bg-border",
                      )}
                    />
                  ))}
                </div>
                <p className="min-h-4 text-[12px] text-subtle">
                  {strength.label ? `Strength: ${strength.label}` : "Strength shows as you type."}
                </p>
              </div>
            </div>
            <div className="space-y-2.5">
              <PasswordField
                label="Confirm new password"
                autoComplete="new-password"
                value={form.confirm}
                onChange={update("confirm")}
                error={shown("confirm")}
              />
              <ul className="space-y-1 text-[12.5px]">
                <Rule ok={long}>At least {MIN_PASSWORD} characters</Rule>
                <Rule ok={matches}>Both entries match</Rule>
              </ul>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" loading={busy}>
              Update password
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setOpen(false);
                setForm({ current: "", next: "", confirm: "" });
                setTouched(false);
                setError(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      )}
    </SettingsSection>
  );
}

function Rule({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <li className={cn("flex items-center gap-1.5", ok ? "text-success" : "text-subtle")}>
      {ok ? (
        <Check aria-hidden className="size-3.5" />
      ) : (
        <Circle aria-hidden className="size-3.5" />
      )}
      {children}
      <span className="sr-only">{ok ? " (done)" : " (not yet)"}</span>
    </li>
  );
}
