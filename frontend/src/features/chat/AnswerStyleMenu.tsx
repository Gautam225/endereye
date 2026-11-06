import { Gauge, Layers, Zap } from "lucide-react";

import { Select, type SelectOption } from "../../components/ui/Select";
import { setAnswerStyle, useAnswerStyle, type AnswerStyle } from "./answerStyle";

const OPTIONS: SelectOption[] = [
  {
    value: "quick",
    label: "Quick",
    icon: <Zap />,
    description: "A faster model for simple lookups. Fewer checks.",
  },
  {
    value: "standard",
    label: "Standard",
    icon: <Gauge />,
    description: "One checked query, with the answer explained.",
  },
  {
    value: "deep",
    label: "Deep",
    icon: <Layers />,
    description: "Splits a big request into separate analyses, each shown on its own.",
  },
];

/**
 * How the next question is answered: one small menu beside the send button. Deep splits a request
 * into analyses of tables, so the general chat (no tables) offers only Quick and Standard.
 */
export function AnswerStyleMenu({ deep = true }: { deep?: boolean }) {
  const chosen = useAnswerStyle();
  const style = chosen === "deep" && !deep ? "standard" : chosen;
  return (
    <Select
      variant="pill"
      align="end"
      menuWidth={300}
      ariaLabel="How to answer"
      options={deep ? OPTIONS : OPTIONS.filter((option) => option.value !== "deep")}
      value={style}
      onChange={(event) => setAnswerStyle(event.target.value as AnswerStyle)}
    />
  );
}
