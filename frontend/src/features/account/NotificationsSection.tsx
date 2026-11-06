import { Bell, BellOff, BellRing } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "../../components/ui/Button";
import { Skeleton } from "../../components/ui/Skeleton";
import { Switch } from "../../components/ui/Switch";
import { cn } from "../../lib/cn";
import {
  isQuiet,
  pauseEnds,
  pausedUntilText,
  usePreferences,
  useResetPreferences,
  useSendTestNotification,
  useUpdatePreferences,
  type Category,
  type PauseChoice,
  type Preferences,
} from "../notifications/preferences";
import { SettingsSection } from "./SettingsSection";

const PAUSES: Array<{ id: PauseChoice; label: string }> = [
  { id: "hour", label: "1 hour" },
  { id: "four-hours", label: "4 hours" },
  { id: "tomorrow", label: "Until tomorrow" },
];

/**
 * Which pop-ups appear while you work. Everything is on to begin with. A switch takes effect and
 * is saved the moment it is touched; there is nothing to confirm. One master switch and a short
 * pause cover the "not now" cases, so the individual switches stay for the lasting choices.
 */
export function NotificationsSection() {
  const prefs = usePreferences();

  return (
    <SettingsSection
      id="notifications"
      title="Notifications"
      description="Choose which pop-ups appear in the corner of the screen while you work."
      footer="Messages about something you just did, such as a failed upload, always appear."
    >
      {prefs.isPending ? (
        <div className="space-y-3 p-5">
          <Skeleton className="h-14" />
          <Skeleton className="h-32" />
        </div>
      ) : prefs.isError ? (
        <p className="p-5 text-[13px] text-muted">
          Your notification settings could not be loaded. {prefs.error.message}
        </p>
      ) : (
        <Controls prefs={prefs.data} />
      )}
    </SettingsSection>
  );
}

function Controls({ prefs }: { prefs: Preferences }) {
  const update = useUpdatePreferences();
  const reset = useResetPreferences();
  const test = useSendTestNotification();
  const [confirmingReset, setConfirmingReset] = useState(false);
  const quiet = isQuiet(prefs);
  const paused = prefs.enabled && prefs.paused_until !== null && quiet ? prefs.paused_until : null;
  const groups = groupsOf(prefs.categories);
  const changed = prefs.categories.some((c) => !c.enabled) || !prefs.enabled || paused !== null;

  return (
    <>
      <Master
        enabled={prefs.enabled}
        paused={paused}
        onToggle={(enabled) => update.mutate({ enabled })}
        onPause={(choice) => update.mutate({ paused_until: pauseEnds(choice).toISOString() })}
        onResume={() => update.mutate({ clear_pause: true })}
      />

      {groups.map((group) => (
        <section
          key={group.name}
          aria-label={group.name}
          className={cn("transition-opacity duration-200", quiet && "opacity-50")}
        >
          <h3 className="flex items-baseline justify-between gap-3 px-5 pt-4 pb-1 text-[11.5px] font-semibold tracking-wider text-subtle uppercase">
            {group.name}
            <span className="font-normal tracking-normal normal-case">
              {group.items.filter((c) => c.enabled).length} of {group.items.length} on
            </span>
          </h3>
          <ul>
            {group.items.map((category) => (
              <Row
                key={category.id}
                category={category}
                disabled={!prefs.enabled}
                onChange={(enabled) => update.mutate({ categories: { [category.id]: enabled } })}
              />
            ))}
          </ul>
        </section>
      ))}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-3 bg-surface-2/40 px-5 py-3">
        <p aria-live="polite" className="min-w-0 flex-1 text-[12.5px] text-subtle">
          {update.isPending
            ? "Saving…"
            : update.isError
              ? "Not saved. Please try again."
              : "Saved as you change them."}
        </p>
        {changed &&
          (confirmingReset ? (
            <span className="flex items-center gap-1.5 text-[13px]">
              <span className="text-muted">Turn everything back on?</span>
              <Button size="sm" variant="ghost" onClick={() => setConfirmingReset(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                loading={reset.isPending}
                onClick={() =>
                  reset.mutate(undefined, { onSuccess: () => setConfirmingReset(false) })
                }
              >
                Reset
              </Button>
            </span>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setConfirmingReset(true)}>
              Reset to defaults
            </Button>
          ))}
        <Button size="sm" loading={test.isPending} onClick={() => test.mutate()}>
          <Bell aria-hidden className="size-3.5" />
          Send a test
        </Button>
      </div>
    </>
  );
}

// ── The master control ───────────────────────────────────────────────────────

function Master({
  enabled,
  paused,
  onToggle,
  onPause,
  onResume,
}: {
  enabled: boolean;
  paused: string | null;
  onToggle: (enabled: boolean) => void;
  onPause: (choice: PauseChoice) => void;
  onResume: () => void;
}) {
  const labelId = useId();
  const on = enabled && paused === null;
  const Icon = on ? BellRing : BellOff;

  return (
    <div className="space-y-3 px-5 py-4">
      <div className="flex items-center gap-3.5">
        <Icon
          aria-hidden
          className={cn("size-5 shrink-0 transition-colors", on ? "text-accent" : "text-subtle")}
        />
        <div className="min-w-0 flex-1">
          <p id={labelId} className="text-[14.5px] leading-5 font-semibold">
            Pop-up notifications
          </p>
          <p className="text-[13px] leading-5 text-muted">
            {!enabled
              ? "Off. You will not get any pop-ups."
              : paused
                ? `Paused until ${pausedUntilText(paused)}.`
                : "On. You will hear about the things below."}
          </p>
        </div>
        <Switch checked={enabled} onChange={onToggle} aria-labelledby={labelId} />
      </div>

      {enabled && (
        <div className="flex flex-wrap items-center gap-2 pl-[34px]">
          {paused ? (
            <Button size="sm" onClick={onResume}>
              Resume now
            </Button>
          ) : (
            <>
              <span className="text-[13px] text-muted">Pause for</span>
              {PAUSES.map((pause) => (
                <button
                  key={pause.id}
                  type="button"
                  onClick={() => onPause(pause.id)}
                  className="rounded-md border border-border px-2.5 py-1 text-[12.5px] font-medium text-muted transition-colors hover:border-border-strong hover:bg-surface-2 hover:text-fg focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none"
                >
                  {pause.label}
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── One kind of notification ─────────────────────────────────────────────────

function Row({
  category,
  disabled,
  onChange,
}: {
  category: Category;
  disabled: boolean;
  onChange: (enabled: boolean) => void;
}) {
  const id = useId();

  return (
    <li>
      {/* The whole row is the target, not only the switch: easier to hit, and a click anywhere on it does what it says. */}
      <label
        htmlFor={id}
        className={cn(
          "flex items-center gap-4 px-5 py-3 transition-colors",
          disabled ? "cursor-not-allowed" : "cursor-pointer hover:bg-surface-2/50",
        )}
      >
        <span className="min-w-0 flex-1">
          <span id={`${id}-title`} className="block text-[14px] leading-5 font-medium">
            {category.title}
          </span>
          <span id={`${id}-about`} className="block text-[13px] leading-5 text-muted">
            {category.description}
          </span>
        </span>
        <Switch
          id={id}
          checked={category.enabled}
          disabled={disabled}
          onChange={onChange}
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-about`}
        />
      </label>
    </li>
  );
}

/** The categories grouped as the server names them, in the order they arrive. */
function groupsOf(categories: Category[]) {
  const groups: Array<{ name: string; items: Category[] }> = [];
  for (const category of categories) {
    let group = groups.find((g) => g.name === category.group);
    if (!group) {
      group = { name: category.group, items: [] };
      groups.push(group);
    }
    group.items.push(category);
  }
  return groups;
}
