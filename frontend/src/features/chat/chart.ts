import type { ChartSpec, ResultColumn } from "./types";
import { isNumericType } from "../spaces/cells";

export const SERIES_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
];
export const MAX_SERIES = SERIES_COLORS.length;

export type Row = Record<string, string | number | null>;

export { isNumericType };

export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

/** "2025-01-01T00:00:00" becomes "2025-01-01"; empty values get a label. */
export function categoryLabel(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(empty)";
  const text = String(value);
  return /^\d{4}-\d{2}-\d{2}T/.test(text) ? text.slice(0, 10) : text;
}

export interface ChartData {
  rows: Row[];
  /** The keys to draw: the value columns, or one per series value. */
  keys: string[];
}

/** Turns result rows into what the chart library draws. Only real values; nothing is added. */
export function chartData(spec: ChartSpec, columns: ResultColumn[], rows: unknown[][]): ChartData {
  const index = (name: string | null) => (name ? columns.findIndex((c) => c.name === name) : -1);
  const x = index(spec.x);

  if (spec.series && spec.y[0]) {
    const series = index(spec.series);
    const value = index(spec.y[0]);
    const byX = new Map<string, Row>();
    const keys: string[] = [];
    for (const row of rows) {
      const label = categoryLabel(row[x]);
      const key = categoryLabel(row[series]);
      if (!keys.includes(key)) keys.push(key);
      const target = byX.get(label) ?? { x: label };
      target[key] = toNumber(row[value]);
      byX.set(label, target);
    }
    return { rows: [...byX.values()], keys: keys.slice(0, MAX_SERIES) };
  }

  const value = spec.y.map(index);
  const points = rows.map((row) => {
    const out: Row = { x: spec.type === "scatter" ? toNumber(row[x]) : categoryLabel(row[x]) };
    spec.y.forEach((name, i) => {
      out[name] = toNumber(row[value[i] ?? -1]);
    });
    return out;
  });
  const first = spec.y[0];
  return {
    rows: spec.sort === "value" && first ? rankedByValue(points, first) : points,
    keys: spec.y,
  };
}

/** Largest first; a missing value goes last, and equal values keep the order of the query. */
function rankedByValue(rows: Row[], key: string): Row[] {
  const size = (row: Row) => {
    const value = row[key];
    return typeof value === "number" ? value : -Infinity;
  };
  return [...rows].sort((a, b) => {
    const [left, right] = [size(a), size(b)];
    return left === right ? 0 : right > left ? 1 : -1;
  });
}

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const compactExact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 2 });
const full = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });

export function compactNumber(value: unknown): string {
  const number = toNumber(value);
  return number === null ? "" : compact.format(number);
}

export function fullNumber(value: unknown): string {
  const number = toNumber(value);
  return number === null ? "-" : full.format(number);
}

/** A figure written on a bar or a tile: as it is, except millions and more, which are shortened. */
export function labelNumber(value: unknown): string {
  const number = toNumber(value);
  if (number === null) return "";
  return Math.abs(number) >= 1e6 ? compactExact.format(number) : full.format(number);
}

/** What an overall figure is, in a word or two, from the kind of column it is. */
export function totalCaption(kind: string): string {
  switch (kind) {
    case "avg":
      return "Overall average";
    case "min":
      return "Overall lowest";
    case "max":
      return "Overall highest";
    case "count":
    case "sum":
      return "Total";
    default:
      return "Overall";
  }
}

/** Short forms that read badly on a chart, spelled out. */
const WORDS: Record<string, string> = {
  cnt: "count",
  qty: "quantity",
  amt: "amount",
  num: "number",
  pct: "percent",
  avg: "average",
  tot: "total",
};

/** Column names in snake_case read better as "Snake case"; "employee_cnt" as "Employee count". */
export function prettyName(name: string): string {
  const text = name
    .replace(/_/g, " ")
    .trim()
    .split(/\s+/)
    .map((word) => WORDS[word.toLowerCase()] ?? word)
    .join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Column names that say nothing about what the axis shows. */
const GENERIC_AXIS = new Set(["label", "category", "name", "key", "item", "x"]);

/** Measure columns that say nothing (the analysis is named elsewhere), so no axis is titled by them. */
const GENERIC_MEASURE = new Set(["value", "values", "metric", "result", "measure", "number"]);

export function isGenericMeasure(name: string): boolean {
  return GENERIC_MEASURE.has(name.toLowerCase());
}

/** The title of the value axis, or "" when the column's name would only be noise. */
export function valueTitle(spec: ChartSpec): string {
  const only = spec.y.length === 1 ? spec.y[0] : undefined;
  return only && !isGenericMeasure(only) ? prettyName(only) : "";
}

/** The title of the x axis, or "" when the column's name would only be noise. */
export function axisTitle(spec: ChartSpec): string {
  if (spec.xLabel) return spec.xLabel;
  return spec.x && !GENERIC_AXIS.has(spec.x.toLowerCase()) ? prettyName(spec.x) : "";
}

/** One chart to draw: its own spec (title and type) and the rows that belong to it. */
export interface ChartPanelView {
  key: string;
  spec: ChartSpec;
  rows: unknown[][];
}

/** Years and dates sort as text; other labels keep the order of the query. */
function sortedByLabel(rows: unknown[][], x: number): unknown[][] {
  return [...rows].sort((a, b) =>
    categoryLabel(a[x]).localeCompare(categoryLabel(b[x]), undefined, { numeric: true }),
  );
}

/**
 * The charts for a result: one, or one for each kind of figure (an average, a count and a total
 * each have their own axis, with every row), or, when the result stacks several separate analyses
 * (a column names the analysis), one per analysis with only that analysis's rows. A chart that
 * runs over time is put in time order. Nothing is added: every chart reads the real rows.
 */
export function panelsOf(
  spec: ChartSpec,
  columns: ResultColumn[],
  rows: unknown[][],
): ChartPanelView[] {
  if (spec.panels && spec.panels.length > 0 && !spec.facet) {
    return spec.panels.map((panel, position) => ({
      key: panel.y?.join(",") ?? String(position),
      spec: {
        ...spec,
        type: panel.type,
        title: panel.title,
        y: panel.y ?? spec.y,
        sort: panel.sort ?? null,
        note: panel.note,
        colorIndex: position,
        panels: undefined,
        totals: undefined,
        omitted: undefined,
      },
      rows,
    }));
  }
  const facet = spec.facet ? columns.findIndex((c) => c.name === spec.facet) : -1;
  if (!spec.panels || spec.panels.length === 0 || facet < 0) {
    return [{ key: "chart", spec, rows }];
  }
  const x = columns.findIndex((c) => c.name === spec.x);
  return spec.panels.map((panel, position) => {
    const analysis = panel.value ?? "";
    const own = rows.filter((row) => String(row[facet]) === analysis);
    return {
      key: analysis,
      spec: {
        ...spec,
        type: panel.type,
        title: panel.title,
        facet: null,
        panels: undefined,
        xLabel: analysis,
        note: panel.note,
        colorIndex: position,
      },
      rows: panel.type === "line" && x >= 0 ? sortedByLabel(own, x) : own,
    };
  });
}
