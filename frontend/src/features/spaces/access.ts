export type RuleKind = "hide_column" | "mask_column" | "row_filter";
export type Audience = "viewers" | "members" | "everyone";

export interface AccessRule {
  id: string;
  table_id: string;
  table: string;
  kind: RuleKind;
  column: string | null;
  expression: string | null;
  audience: Audience;
  user_id: string | null;
  user_email: string | null;
  created_at: string;
}

export interface AccessRuleDraft {
  table_id: string;
  kind: RuleKind;
  column?: string | null;
  expression?: string | null;
  audience: Audience;
  user_id?: string | null;
}

export const KIND_OPTIONS: Array<{ value: RuleKind; label: string; help: string }> = [
  {
    value: "hide_column",
    label: "Hide a column",
    help: "The column does not exist for them: not in a table, not in SELECT *, not in a query.",
  },
  {
    value: "mask_column",
    label: "Show a column as empty",
    help: "The column is there, but every value reads as empty. Use it when queries need the column.",
  },
  {
    value: "row_filter",
    label: "Show only some rows",
    help: "They only ever see the rows that meet a condition, whatever they ask or join.",
  },
];

export const AUDIENCE_OPTIONS: Array<{ value: Audience; label: string }> = [
  { value: "viewers", label: "Viewers of this space" },
  { value: "members", label: "Viewers and editors (not admins)" },
  { value: "everyone", label: "Everyone, admins too" },
];

/** Who a rule is for, in words. */
export function whoText(rule: Pick<AccessRule, "audience" | "user_id" | "user_email">): string {
  if (rule.user_id) return rule.user_email ?? "one person";
  return AUDIENCE_OPTIONS.find((option) => option.value === rule.audience)?.label ?? rule.audience;
}

/** What a rule does, in one line: "Hide unit_price of sales". */
export function ruleText(
  rule: Pick<AccessRule, "kind" | "table" | "column" | "expression">,
): string {
  switch (rule.kind) {
    case "hide_column":
      return `Hide ${rule.column ?? "a column"} of ${rule.table}`;
    case "mask_column":
      return `Show ${rule.column ?? "a column"} of ${rule.table} as empty`;
    case "row_filter":
      return `Only the rows of ${rule.table} where ${rule.expression ?? "…"}`;
  }
}

/** Whether the draft can be sent: every kind needs its own piece. */
export function draftProblem(
  draft: Partial<AccessRuleDraft>,
  who: "audience" | "person",
): string | null {
  if (!draft.table_id) return "Choose a table.";
  if (draft.kind === "row_filter" && !draft.expression?.trim()) {
    return "Write the condition the rows must meet.";
  }
  if (draft.kind !== "row_filter" && !draft.column) return "Choose a column.";
  if (who === "person" && !draft.user_id) return "Choose a person.";
  return null;
}
