import { Monitor, Moon, Sun } from "lucide-react";
import { useId } from "react";

import { SegmentedControl, type SegmentOption } from "../../components/ui/SegmentedControl";
import { cn } from "../../lib/cn";
import { PALETTES, type PaletteId } from "../../lib/palettes";
import { useTheme, type ResolvedTheme, type ThemePreference } from "../../lib/theme";
import { SettingRow, SettingsSection } from "./SettingsSection";

const MODES: SegmentOption<ThemePreference>[] = [
  { value: "system", label: "System", icon: <Monitor /> },
  { value: "light", label: "Light", icon: <Sun /> },
  { value: "dark", label: "Dark", icon: <Moon /> },
];

/** Light or dark, and the colors. Both apply at once and are remembered in this browser. */
export function AppearanceSection() {
  const { preference, setPreference, resolved, palette, setPalette } = useTheme();
  const labelId = useId();

  return (
    <SettingsSection
      id="appearance"
      title="Appearance"
      description="Light or dark, and the colors of the app. Saved in this browser."
      footer="System follows your device's light or dark setting."
    >
      <SettingRow title="Mode" description="Match your device, or choose one.">
        <SegmentedControl
          label="Mode"
          options={MODES}
          value={preference}
          onChange={setPreference}
        />
      </SettingRow>

      <div className="space-y-3 px-5 py-4">
        <div>
          <p id={labelId} className="text-[14px] leading-5 font-medium">
            Colors
          </p>
          <p className="mt-0.5 text-[13px] leading-5 text-muted">
            Every color of the app changes, in light and in dark.
          </p>
        </div>
        <div role="radiogroup" aria-labelledby={labelId} className="flex flex-wrap gap-2.5">
          {PALETTES.map((option) => (
            <Swatch
              key={option.id}
              id={option.id}
              name={option.name}
              about={option.description}
              mode={resolved}
              selected={option.id === palette}
              onSelect={() => setPalette(option.id)}
            />
          ))}
        </div>
      </div>
    </SettingsSection>
  );
}

/** One color scheme as a small radio chip: three of its own colors, and its name. */
function Swatch({
  id,
  name,
  about,
  mode,
  selected,
  onSelect,
}: {
  id: PaletteId;
  name: string;
  about: string;
  mode: ResolvedTheme;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <label className="cursor-pointer" title={about}>
      <input
        type="radio"
        name="color-template"
        value={id}
        checked={selected}
        onChange={onSelect}
        className="peer sr-only"
      />
      <span
        className={cn(
          "flex items-center gap-2.5 rounded-lg border bg-surface py-2 pr-3.5 pl-2 transition-colors duration-150",
          "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent",
          selected
            ? "border-accent bg-accent-soft ring-1 ring-accent"
            : "border-border hover:border-border-strong hover:bg-surface-2/60",
        )}
      >
        {/* It carries its own palette, so the three bands are that scheme's real colors. */}
        <span
          aria-hidden
          data-palette={id}
          data-theme={mode}
          className="flex h-7 w-11 overflow-hidden rounded-md border border-border"
        >
          <span className="flex-1 bg-bg" />
          <span className="w-3 bg-surface" />
          <span className="w-3 bg-accent" />
        </span>
        <span className="text-[13.5px] font-medium">{name}</span>
        <span className="sr-only">. {about}</span>
      </span>
    </label>
  );
}
