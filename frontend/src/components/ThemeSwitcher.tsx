import { Monitor, Moon, Sun } from "lucide-react";

import { useTheme, type ThemePreference } from "../lib/theme";
import { SegmentedControl, type SegmentOption } from "./ui/SegmentedControl";

const OPTIONS: SegmentOption<ThemePreference>[] = [
  { value: "system", label: "System theme", icon: <Monitor /> },
  { value: "light", label: "Light theme", icon: <Sun /> },
  { value: "dark", label: "Dark theme", icon: <Moon /> },
];

export function ThemeSwitcher() {
  const { preference, setPreference } = useTheme();
  return (
    <SegmentedControl
      label="Theme"
      options={OPTIONS}
      value={preference}
      onChange={setPreference}
      iconOnly
    />
  );
}
