import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router";

/**
 * A notification can point at one report or one alert (`?report=<id>`). That card scrolls into
 * view, opens, and glows for a moment, so the person lands on the exact thing it was about.
 */
export function useDeepLink(param: string, id: string) {
  const [params] = useSearchParams();
  const targeted = params.get(param) === id;
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (targeted) ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [targeted]);

  return [ref, targeted] as const;
}
