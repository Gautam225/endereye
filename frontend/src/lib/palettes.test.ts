/// <reference types="node" />
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { DEFAULT_PALETTE, PALETTE_STORAGE_KEY, PALETTES, parsePalette } from "./palettes";

type Tokens = Record<string, string>;

// Read from disk: Vitest turns imported CSS into an empty string, even with ?raw.
const read = (relative: string) => readFileSync(new URL(relative, import.meta.url), "utf8");
const stylesheet = read("../styles/index.css");
const indexHtml = read("../../index.html");

/** Every rule in the stylesheet that declares custom properties, keyed by selector. */
function readRules(source: string): Map<string, Tokens> {
  const rules = new Map<string, Tokens>();
  const text = source.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const rule of text.matchAll(/([^{};]+)\{([^{}]*)\}/g)) {
    const tokens: Tokens = {};
    for (const declaration of (rule[2] ?? "").matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      tokens[declaration[1] ?? ""] = (declaration[2] ?? "").trim();
    }
    if (!Object.keys(tokens).length) continue;
    for (const selector of (rule[1] ?? "").split(",")) {
      rules.set(selector.trim(), { ...rules.get(selector.trim()), ...tokens });
    }
  }
  return rules;
}

const rules = readRules(stylesheet);
const MODES = ["light", "dark"] as const;
type Mode = (typeof MODES)[number];

function selectorFor(palette: string, mode: Mode): string {
  if (palette === DEFAULT_PALETTE) return mode === "light" ? ":root" : '[data-theme="dark"]';
  return mode === "light"
    ? `[data-palette="${palette}"]`
    : `[data-palette="${palette}"][data-theme="dark"]`;
}

function tokensFor(palette: string, mode: Mode): Tokens {
  const found = rules.get(selectorFor(palette, mode));
  if (!found) throw new Error(`index.css has no ${mode} tokens for "${palette}"`);
  return found;
}

function luminance(hex: string): number {
  const [r = 0, g = 0, b = 0] = [1, 3, 5].map((start) => {
    const channel = parseInt(hex.slice(start, start + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two #rrggbb colors. */
function contrast(a: string, b: string): number {
  const [lighter = 0, darker = 0] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (lighter + 0.05) / (darker + 0.05);
}

function color(tokens: Tokens, name: string): string {
  const value = tokens[name];
  if (!value || !/^#[0-9a-f]{6}$/i.test(value)) throw new Error(`${name} is not a #rrggbb color`);
  return value;
}

const TEXT_TOKENS = [
  "--text",
  "--text-muted",
  "--text-subtle",
  "--accent",
  "--success",
  "--warning",
  "--danger",
];
const SURFACES = ["--bg", "--surface", "--surface-2"];
const CHARTS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5", "--chart-6"];

describe("color templates", () => {
  it("offers the default first, plus Claude and ChatGPT", () => {
    expect(PALETTES.map((palette) => palette.id)).toEqual(["default", "claude", "chatgpt"]);
    expect(PALETTES[0]?.id).toBe(DEFAULT_PALETTE);
  });

  it("gives the default template to a preview that carries data-palette=default", () => {
    expect(rules.get('[data-palette="default"]')).toEqual(rules.get(":root"));
  });

  describe.each(PALETTES.flatMap(({ id }) => MODES.map((mode) => ({ id, mode }))))(
    "$id, $mode",
    ({ id, mode }) => {
      const tokens = tokensFor(id, mode);

      it("defines every token, so nothing falls through to another template", () => {
        const expected = Object.keys(tokensFor(DEFAULT_PALETTE, "light")).sort();
        expect(Object.keys(tokens).sort()).toEqual(expected);
      });

      it.each(TEXT_TOKENS)("%s has AA contrast (4.5:1) on every surface", (name) => {
        for (const surface of SURFACES) {
          expect(
            contrast(color(tokens, name), color(tokens, surface)),
            `${name} on ${surface}`,
          ).toBeGreaterThanOrEqual(4.5);
        }
      });

      it("keeps the label on an accent button readable", () => {
        expect(
          contrast(color(tokens, "--accent-fg"), color(tokens, "--accent")),
        ).toBeGreaterThanOrEqual(4.5);
      });

      it("draws every chart color at 3:1 or better on cards and the page", () => {
        for (const name of CHARTS) {
          for (const surface of ["--surface", "--bg"]) {
            expect(
              contrast(color(tokens, name), color(tokens, surface)),
              `${name} on ${surface}`,
            ).toBeGreaterThanOrEqual(3);
          }
        }
      });

      it("never sets the card shadow to none, which would drop the rings beside it", () => {
        expect(tokens["--card-shadow"]).not.toBe("none");
      });

      it("starts the chart colors with the accent", () => {
        expect(tokens["--chart-1"]).toBe(tokens["--accent"]);
      });
    },
  );
});

describe("saved color template", () => {
  it("falls back to the default for anything it does not know", () => {
    expect(parsePalette(null)).toBe(DEFAULT_PALETTE);
    expect(parsePalette(undefined)).toBe(DEFAULT_PALETTE);
    expect(parsePalette("")).toBe(DEFAULT_PALETTE);
    expect(parsePalette("solarized")).toBe(DEFAULT_PALETTE);
  });

  it("keeps a template it does know", () => {
    expect(parsePalette("claude")).toBe("claude");
    expect(parsePalette("chatgpt")).toBe("chatgpt");
  });

  it("is applied before first paint by index.html, from the same key and ids", () => {
    expect(indexHtml).toContain(`localStorage.getItem("${PALETTE_STORAGE_KEY}")`);
    for (const { id } of PALETTES) {
      if (id !== DEFAULT_PALETTE) expect(indexHtml).toContain(`"${id}"`);
    }
  });
});
