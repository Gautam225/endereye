import { Download } from "lucide-react";
import { useState, type RefObject } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  LabelList,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "../../lib/cn";
import {
  SERIES_COLORS,
  axisTitle,
  chartData,
  compactNumber,
  fullNumber,
  isGenericMeasure,
  labelNumber,
  prettyName,
  totalCaption,
  valueTitle,
  type ChartData,
} from "./chart";
import type { ChartSpec, ChartTotal, ResultColumn } from "./types";
import { useChartDownload } from "./useChartDownload";

const AXIS = { stroke: "var(--border-strong)" };
const TICK = { fill: "var(--text-subtle)", fontSize: 12 };
const TOOLTIP = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    fontSize: 13,
    color: "var(--text)",
  },
  labelStyle: { color: "var(--text-muted)" },
  cursor: { fill: "var(--surface-2)", fillOpacity: 0.6 },
};
const HEIGHT = 320;
const MAX_LABELLED_BARS = 12; // a value above each bar, while there is room for it
const AXIS_TITLE = { fill: "var(--text-muted)", fontSize: 12, fontWeight: 500 };

// Bars that lie down: the names on the left, the value written at the end of each bar.
const BAR_THICKNESS = 18; // one bar of a group
const GROUP_PADDING = 14; // the space around a category's bar or bars
const MAX_LABELLED_ROWS = 20; // a value at the end of each bar, while there is room for it
const MAX_NAME_WIDTH = 168;
const MAX_NAME_CHARS = 26; // a longer name is cut with an ellipsis (the tooltip has all of it)

const shorten = (name: string) =>
  name.length > MAX_NAME_CHARS ? `${name.slice(0, MAX_NAME_CHARS - 1)}…` : name;

const color = (index: number) => SERIES_COLORS[index % SERIES_COLORS.length] ?? SERIES_COLORS[0];

/** A chart of one series takes the color of its place among the charts, so each analysis looks
 * different; the series of one chart keep the colors that tell them apart. */
const paint = (spec: ChartSpec, data: ChartData, index: number) =>
  color((data.keys.length === 1 ? (spec.colorIndex ?? 0) : 0) + index);

/** The result drawn as the chosen chart. Uses the real rows only. */
export function ResultChart({
  spec,
  columns,
  rows,
  name,
  holderRef,
}: {
  spec: ChartSpec;
  columns: ResultColumn[];
  rows: unknown[][];
  /** The title put on the saved picture when the chart has none of its own. */
  name?: string;
  /** Pass this when the caller has its own download button; the chart then has none. */
  holderRef?: RefObject<HTMLDivElement | null>;
}) {
  const data = chartData(spec, columns, rows);
  const label = spec.title || "Chart of the result";
  const own = useChartDownload(spec.title || name || "");
  const holder = holderRef ?? own.ref;

  return (
    <figure className="space-y-2">
      {spec.title && <figcaption className="text-[13.5px] font-medium">{spec.title}</figcaption>}
      {spec.type !== "kpi" && !holderRef && (
        <div data-no-print className="flex items-center justify-end gap-2">
          {own.error && (
            <span role="alert" className="text-[12.5px] text-danger">
              {own.error}
            </span>
          )}
          <button
            type="button"
            onClick={() => void own.save()}
            title="Download this chart as a PNG picture"
            className="flex h-7 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          >
            <Download aria-hidden className="size-3.5" />
            Download PNG
          </button>
        </div>
      )}
      <div ref={holder} role="img" aria-label={`${label}. The same rows are in the Table view.`}>
        {spec.type === "kpi" ? (
          <KpiTiles spec={spec} columns={columns} rows={rows} />
        ) : spec.type === "pie" ? (
          <Pie_ spec={spec} data={data} />
        ) : spec.type === "scatter" ? (
          <Scatter_ spec={spec} data={data} />
        ) : spec.type === "bar" && spec.orientation === "horizontal" ? (
          <HorizontalBars spec={spec} data={data} />
        ) : (
          <Cartesian spec={spec} data={data} />
        )}
      </div>
      {spec.note && <p className="text-[13px] leading-relaxed text-muted">{spec.note}</p>}
      {spec.partial && (
        <p className="text-[12.5px] text-subtle">
          Showing the first {rows.length} rows of the result.
        </p>
      )}
    </figure>
  );
}

/** Which series the legend has switched off. One is always left drawn. */
function useHiddenSeries(total: number) {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else if (next.size < total - 1) next.add(key);
      return next;
    });
  return { hidden, toggle };
}

/** Bars lying down, with the category names on the left, so every name can be read. */
function HorizontalBars({ spec, data }: { spec: ChartSpec; data: ChartData }) {
  const { hidden, toggle } = useHiddenSeries(data.keys.length);
  const bars = data.keys.length;
  const count = data.rows.length;
  const legend = bars > 1;
  const longest = Math.max(0, ...data.rows.map((row) => shorten(String(row.x ?? "")).length));
  const nameWidth = Math.min(MAX_NAME_WIDTH, Math.max(64, Math.round(longest * 6.8) + 14));
  const axisValue = valueTitle(spec);
  const labelled = count <= MAX_LABELLED_ROWS && bars <= 2;
  const height = Math.max(
    200,
    count * (bars * BAR_THICKNESS + GROUP_PADDING) + (axisValue ? 56 : 36) + (legend ? 28 : 0),
  );

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        layout="vertical"
        data={data.rows}
        margin={{ top: 4, right: labelled ? 76 : 16, bottom: 4, left: 4 }}
        barCategoryGap="24%"
        barGap={2}
      >
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" horizontal={false} />
        <XAxis
          type="number"
          tick={TICK}
          axisLine={false}
          tickLine={false}
          tickMargin={4}
          tickFormatter={compactNumber}
          height={axisValue ? 44 : 28}
          label={
            axisValue
              ? { value: axisValue, position: "insideBottom", offset: 0, style: AXIS_TITLE }
              : undefined
          }
        />
        <YAxis
          type="category"
          dataKey="x"
          width={nameWidth}
          tick={TICK}
          axisLine={AXIS}
          tickLine={false}
          interval={0}
          tickFormatter={(name) => shorten(String(name))}
        />
        <Tooltip
          {...TOOLTIP}
          formatter={(value, name) => [fullNumber(value), prettyName(String(name))]}
        />
        {legend && (
          <Legend
            verticalAlign="top"
            align="right"
            wrapperStyle={{ cursor: "pointer", fontSize: 13 }}
            onClick={(entry) => toggle(String(entry.dataKey))}
            formatter={(name) => (
              <span className={hidden.has(String(name)) ? "line-through opacity-40" : undefined}>
                {prettyName(String(name))}
              </span>
            )}
          />
        )}
        {data.keys.map((key, i) => (
          <Bar
            key={key}
            hide={hidden.has(key)}
            dataKey={key}
            fill={paint(spec, data, i)}
            radius={[0, 3, 3, 0]}
            maxBarSize={BAR_THICKNESS + 4}
            isAnimationActive={false}
          >
            {labelled && (
              <LabelList
                dataKey={key}
                position="right"
                formatter={(value: unknown) => labelNumber(value)}
                style={{ fill: "var(--text-muted)", fontSize: 12 }}
              />
            )}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

function Cartesian({ spec, data }: { spec: ChartSpec; data: ChartData }) {
  const { hidden, toggle } = useHiddenSeries(data.keys.length);
  const legend = data.keys.length > 1;
  const common = { data: data.rows, margin: { top: 18, right: 16, bottom: 4, left: 4 } };
  // Every label is shown while they fit, and tilted when they are long, so no year is skipped.
  const count = data.rows.length;
  const longest = Math.max(0, ...data.rows.map((row) => String(row.x ?? "").length));
  const tilted = count > 6 && longest > 6;
  const xTitle = axisTitle(spec);
  const yTitle = valueTitle(spec);
  const labelled = spec.type === "bar" && data.keys.length === 1 && count <= MAX_LABELLED_BARS;
  const axes = (
    <>
      <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
      <XAxis
        dataKey="x"
        tick={TICK}
        axisLine={AXIS}
        tickLine={false}
        tickMargin={6}
        interval={count <= 24 ? 0 : "preserveStartEnd"}
        minTickGap={8}
        angle={tilted ? -35 : 0}
        textAnchor={tilted ? "end" : "middle"}
        height={(tilted ? 62 : 32) + (xTitle ? 22 : 0)}
        label={
          xTitle
            ? { value: xTitle, position: "insideBottom", offset: 0, style: AXIS_TITLE }
            : undefined
        }
      />
      <YAxis
        tick={TICK}
        axisLine={false}
        tickLine={false}
        tickFormatter={compactNumber}
        width={yTitle ? 76 : 56}
        label={
          yTitle
            ? {
                value: yTitle,
                angle: -90,
                position: "insideLeft",
                offset: 4,
                style: { ...AXIS_TITLE, textAnchor: "middle" },
              }
            : undefined
        }
      />
      <Tooltip
        {...TOOLTIP}
        formatter={(value, name) => [fullNumber(value), prettyName(String(name))]}
      />
      {legend && (
        <Legend
          wrapperStyle={{ cursor: "pointer", fontSize: 13, paddingTop: 10 }}
          onClick={(entry) => toggle(String(entry.dataKey))}
          formatter={(name) => (
            <span className={hidden.has(String(name)) ? "line-through opacity-40" : undefined}>
              {prettyName(String(name))}
            </span>
          )}
        />
      )}
    </>
  );

  return (
    <ResponsiveContainer width="100%" height={HEIGHT}>
      {spec.type === "line" ? (
        <LineChart {...common}>
          {axes}
          {data.keys.map((key, i) => (
            <Line
              key={key}
              hide={hidden.has(key)}
              dataKey={key}
              stroke={paint(spec, data, i)}
              strokeWidth={2}
              dot={data.rows.length <= 40}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      ) : spec.type === "area" ? (
        <AreaChart {...common}>
          {axes}
          {data.keys.map((key, i) => (
            <Area
              key={key}
              hide={hidden.has(key)}
              dataKey={key}
              stroke={paint(spec, data, i)}
              fill={paint(spec, data, i)}
              fillOpacity={0.18}
              strokeWidth={2}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      ) : (
        <BarChart {...common} barGap={3} barCategoryGap="22%">
          {axes}
          {data.keys.map((key, i) => (
            <Bar
              key={key}
              hide={hidden.has(key)}
              dataKey={key}
              fill={paint(spec, data, i)}
              radius={[3, 3, 0, 0]}
              maxBarSize={56}
              isAnimationActive={false}
            >
              {labelled && (
                <LabelList
                  dataKey={key}
                  position="top"
                  formatter={(value: unknown) => fullNumber(value)}
                  style={{ fill: "var(--text-muted)", fontSize: 12 }}
                />
              )}
            </Bar>
          ))}
        </BarChart>
      )}
    </ResponsiveContainer>
  );
}

function Pie_({ spec, data }: { spec: ChartSpec; data: ChartData }) {
  const key = spec.y[0] ?? "";
  const slices = data.rows.filter(
    (row) => typeof row[key] === "number" && (row[key] as number) > 0,
  );
  return (
    <ResponsiveContainer width="100%" height={HEIGHT}>
      <PieChart>
        <Pie
          data={slices}
          dataKey={key}
          nameKey="x"
          innerRadius="45%"
          outerRadius="80%"
          paddingAngle={1}
          stroke="var(--surface)"
          isAnimationActive={false}
        >
          {slices.map((row, i) => (
            <Cell key={String(row.x)} fill={color(i)} />
          ))}
        </Pie>
        <Tooltip {...TOOLTIP} formatter={(value) => fullNumber(value)} />
        <Legend />
      </PieChart>
    </ResponsiveContainer>
  );
}

function Scatter_({ spec, data }: { spec: ChartSpec; data: ChartData }) {
  const y = spec.y[0] ?? "";
  return (
    <ResponsiveContainer width="100%" height={HEIGHT}>
      <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
        <XAxis
          dataKey="x"
          type="number"
          name={prettyName(spec.x ?? "")}
          tick={TICK}
          axisLine={AXIS}
          tickLine={false}
          tickFormatter={compactNumber}
        />
        <YAxis
          dataKey={y}
          type="number"
          name={prettyName(y)}
          tick={TICK}
          axisLine={false}
          tickLine={false}
          tickFormatter={compactNumber}
          width={52}
        />
        <Tooltip
          {...TOOLTIP}
          cursor={{ strokeDasharray: "3 3" }}
          formatter={(v) => fullNumber(v)}
        />
        <Scatter data={data.rows} fill={paint(spec, data, 0)} isAnimationActive={false} />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

/**
 * The overall figures of a result that compares several measures: the total head count, the
 * overall average salary and so on. Each was asked of the database over all the rows (never added
 * up here, which would be wrong for an average), so it can be checked against the table.
 */
export function TotalsTiles({ totals }: { totals: ChartTotal[] }) {
  return (
    <div
      role="group"
      aria-label="Overall figures"
      className="grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] gap-3"
    >
      {totals.map((total) => (
        <div
          key={total.name}
          title={fullNumber(total.value)}
          className="rounded-lg border border-border bg-surface-2/50 p-4"
        >
          <p className="text-[11px] font-medium tracking-wide text-subtle uppercase">
            {totalCaption(total.kind)}
          </p>
          <p className="mt-1 text-[24px] leading-tight font-semibold tabular-nums">
            {labelNumber(total.value)}
          </p>
          <p className="mt-0.5 text-[13px] text-muted">{prettyName(total.name)}</p>
        </div>
      ))}
    </div>
  );
}

function KpiTiles({
  spec,
  columns,
  rows,
}: {
  spec: ChartSpec;
  columns: ResultColumn[];
  rows: unknown[][];
}) {
  const row = rows[0] ?? [];
  return (
    <div className={cn("grid gap-3", spec.y.length > 1 && "sm:grid-cols-2")}>
      {spec.y.map((name) => {
        const value = row[columns.findIndex((c) => c.name === name)];
        // A column called "value" says nothing: the row's own label (Overall, Total) does.
        const own = spec.x ? row[columns.findIndex((c) => c.name === spec.x)] : null;
        const caption = isGenericMeasure(name) && own != null ? String(own) : prettyName(name);
        return (
          <div key={name} className="rounded-lg border border-border bg-surface-2/50 p-4">
            <p className="text-[13px] text-muted">{caption}</p>
            <p className="mt-1 text-[26px] font-semibold tabular-nums">{fullNumber(value)}</p>
          </div>
        );
      })}
    </div>
  );
}
