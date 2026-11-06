import { useCallback, useRef, useState } from "react";

import { downloadChartPng } from "./chartPng";

/** Saving the chart drawn inside `ref` as a PNG; `error` says why if that did not work. */
export function useChartDownload(title: string) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  const save = useCallback(async () => {
    if (!ref.current) return;
    setError(null);
    try {
      await downloadChartPng(ref.current, title);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "The chart could not be saved.");
    }
  }, [title]);

  return { ref, save, error };
}
