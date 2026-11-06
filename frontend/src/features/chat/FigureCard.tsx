import { Download } from "lucide-react";
import { useMemo } from "react";

import { Button } from "../../components/ui/Button";
import { ResultChart } from "./ResultChart";
import type { ChartSpec, Figure, ResultColumn } from "./types";
import { useChartDownload } from "./useChartDownload";

/**
 * A chart of numbers the assistant found in a document: one chart, chosen by the assistant for
 * what the numbers are, with its key points and a single button to download it as a picture.
 * Hover (or use the arrow keys after clicking the chart) to read each value. The server has
 * already checked that every number is stated in the document.
 */
export function FigureCard({ figure }: { figure: Figure }) {
  const download = useChartDownload(figure.title);

  const { columns, rows, spec } = useMemo(() => {
    const first = figure.x_label.trim() || "Item";
    const names = figure.series.map((s) => s.name);
    const xName = names.includes(first) ? `${first} (label)` : first;
    const columns: ResultColumn[] = [
      { name: xName, type: "VARCHAR" },
      ...names.map((name) => ({ name, type: "DOUBLE" })),
    ];
    const rows = figure.labels.map((label, index) => [
      label,
      ...figure.series.map((s) => s.values[index] ?? null),
    ]);
    const spec: ChartSpec = {
      type: figure.type === "pie" && names.length > 1 ? "bar" : figure.type,
      x: xName,
      y: figure.type === "pie" ? names.slice(0, 1) : names,
      series: null,
      title: "",
    };
    return { columns, rows, spec };
  }, [figure]);

  return (
    <figure className="overflow-hidden rounded-xl border border-border bg-surface">
      <figcaption className="flex items-center gap-3 px-4 pt-3.5">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-semibold">{figure.title}</p>
          {figure.y_label && <p className="truncate text-[12px] text-subtle">{figure.y_label}</p>}
        </div>
        <Button size="sm" variant="ghost" onClick={() => void download.save()}>
          <Download aria-hidden className="size-3.5" />
          Download PNG
        </Button>
      </figcaption>
      {download.error && (
        <p role="alert" className="px-4 pt-1 text-[12.5px] text-danger">
          {download.error}
        </p>
      )}

      <div className="px-3 pt-4 pb-2 sm:px-4">
        <ResultChart
          spec={spec}
          columns={columns}
          rows={rows}
          name={figure.title}
          holderRef={download.ref}
        />
      </div>

      {figure.key_points.length > 0 && (
        <div className="border-t border-border bg-surface-2/30 px-4 py-3.5">
          <p className="mb-2 text-[11px] font-semibold tracking-wide text-subtle uppercase">
            Key points
          </p>
          <ul className="space-y-1.5">
            {figure.key_points.map((point) => (
              <li key={point} className="flex gap-2.5 text-[14px] leading-6">
                <span aria-hidden className="mt-2.5 size-1.5 shrink-0 rounded-full bg-accent" />
                {point}
              </li>
            ))}
          </ul>
        </div>
      )}
    </figure>
  );
}
