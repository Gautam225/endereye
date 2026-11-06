/**
 * The color templates a person can choose in Account > Appearance. The colors themselves live in
 * src/styles/index.css, one block per template and mode, keyed by the data-palette attribute.
 */
export type PaletteId = "default" | "claude" | "chatgpt";

export interface PaletteInfo {
  id: PaletteId;
  name: string;
  description: string;
}

export const PALETTES: readonly PaletteInfo[] = [
  {
    id: "default",
    name: "Default",
    description: "Teal on soft neutrals. The original Eye of Ender look.",
  },
  {
    id: "claude",
    name: "Claude",
    description: "Warm ivory and charcoal with a clay accent, in the style of Claude.",
  },
  {
    id: "chatgpt",
    name: "ChatGPT",
    description: "Neutral grays and a green accent, in the style of ChatGPT.",
  },
];

export const DEFAULT_PALETTE: PaletteId = "default";

/** Where the choice is remembered; also read by the inline script in index.html. */
export const PALETTE_STORAGE_KEY = "eoe-palette";

/** The saved value, or the default when it is missing or not a template we have. */
export function parsePalette(saved: string | null | undefined): PaletteId {
  return PALETTES.find((palette) => palette.id === saved)?.id ?? DEFAULT_PALETTE;
}
