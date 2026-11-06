import { Eye, EyeOff } from "lucide-react";
import { useId, useState, type ChangeEvent, type ComponentProps, type ReactNode } from "react";

import { cn } from "../../lib/cn";
import { Select, type SelectOption } from "./Select";

const inputClass = cn(
  "block h-9 w-full rounded-md border border-border bg-bg px-3 text-[14px] text-fg",
  "transition-[border-color,box-shadow] duration-150 placeholder:text-subtle",
  "hover:border-border-strong focus-visible:border-accent focus-visible:ring-2",
  "focus-visible:ring-accent/25 focus-visible:outline-none",
  "aria-invalid:border-danger/70 disabled:opacity-60",
);

interface FieldShellProps {
  id: string;
  label: string;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
}

function FieldShell({ id, label, hint, error, children }: FieldShellProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-message`} className="text-[12.5px] text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-message`} className="text-[12.5px] text-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

type InputProps = Omit<ComponentProps<"input">, "id"> & {
  label: string;
  hint?: ReactNode;
  error?: string;
};

export function TextField({ label, hint, error, className, ...input }: InputProps) {
  const id = useId();
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${id}-message` : undefined}
        className={cn(inputClass, className)}
        {...input}
      />
    </FieldShell>
  );
}

export function PasswordField({
  label,
  hint,
  error,
  className,
  ...input
}: Omit<InputProps, "type">) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <div className="relative">
        <input
          id={id}
          type={visible ? "text" : "password"}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || hint ? `${id}-message` : undefined}
          className={cn(inputClass, "pr-10", className)}
          {...input}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
          className="absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-r-md text-subtle transition-colors hover:text-fg"
        >
          {visible ? (
            <EyeOff aria-hidden className="size-4" />
          ) : (
            <Eye aria-hidden className="size-4" />
          )}
        </button>
      </div>
    </FieldShell>
  );
}

type SelectProps = {
  label: string;
  hideLabel?: boolean;
  options: SelectOption[];
  value?: string;
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void;
  disabled?: boolean;
  className?: string;
  name?: string;
};

/** A labelled drop-down. It looks the same in every browser (see Select.tsx). */
export function SelectField({ label, hideLabel, options, className, ...select }: SelectProps) {
  const id = useId();
  return (
    <div className={cn(!hideLabel && "space-y-1.5")}>
      <label
        id={`${id}-label`}
        htmlFor={id}
        className={cn(hideLabel ? "sr-only" : "block text-[13px] font-medium")}
      >
        {label}
      </label>
      <Select id={id} labelId={`${id}-label`} options={options} className={className} {...select} />
    </div>
  );
}

/** An input whose label is given with `aria-label` (for dense rows where a visible label repeats). */
export function BareInput({ className, ...input }: ComponentProps<"input">) {
  return <input className={cn(inputClass, className)} {...input} />;
}

export function BareTextArea({ className, ...area }: ComponentProps<"textarea">) {
  return <textarea className={cn(inputClass, "h-auto min-h-16 py-2", className)} {...area} />;
}
