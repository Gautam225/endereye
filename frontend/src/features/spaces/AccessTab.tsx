import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { SelectField, TextField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { apiGet, apiSend, asApiError } from "../../lib/api";
import {
  AUDIENCE_OPTIONS,
  KIND_OPTIONS,
  draftProblem,
  ruleText,
  whoText,
  type AccessRule,
  type AccessRuleDraft,
  type Audience,
  type RuleKind,
} from "./access";
import { useDirectory, useTables } from "./queries";
import type { Space } from "./types";

const rulesKey = (spaceId: string) => ["spaces", spaceId, "access-rules"] as const;

function useAccessRules(spaceId: string) {
  return useQuery({
    queryKey: rulesKey(spaceId),
    queryFn: () => apiGet<AccessRule[]>(`/spaces/${spaceId}/access-rules`),
  });
}

function useAddRule(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (draft: AccessRuleDraft) =>
      apiSend<AccessRule>("POST", `/spaces/${spaceId}/access-rules`, draft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: rulesKey(spaceId) }),
  });
}

function useDeleteRule(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ruleId: string) =>
      apiSend<void>("DELETE", `/spaces/${spaceId}/access-rules/${ruleId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: rulesKey(spaceId) }),
  });
}

/** What each person may read: admins only, since an editor could lift the rule that limits them. */
export function AccessTab({ space }: { space: Space }) {
  const rules = useAccessRules(space.id);
  const remove = useDeleteRule(space.id);

  return (
    <div className="space-y-5">
      <Notice title="Rules are enforced where the data is read">
        They hold for the assistant, the SQL tab and previews alike, in joins and sub-queries too.
        Admins are only affected by rules written for everyone or for them by name.
      </Notice>
      <AddRule space={space} />
      <Card>
        <CardHeader title="Rules" description="Applied to every question and query, at once." />
        {rules.isPending ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-11" />
          </div>
        ) : rules.isError ? (
          <div className="p-5">
            <Notice tone="error" title="Could not load the rules">
              {rules.error.message}
            </Notice>
          </div>
        ) : rules.data.length === 0 ? (
          <p className="px-5 py-6 text-center text-[13px] text-muted">
            No rules yet: everyone with access to this space reads every column and row.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {rules.data.map((rule) => (
              <li key={rule.id} className="flex items-center gap-3 px-5 py-3">
                <ShieldCheck aria-hidden className="size-4 shrink-0 text-accent" />
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] break-words">{ruleText(rule)}</p>
                  <p className="text-[12.5px] text-subtle">For {whoText(rule)}</p>
                </div>
                <Badge tone="neutral">
                  {KIND_OPTIONS.find((k) => k.value === rule.kind)?.label}
                </Badge>
                <Button
                  size="icon"
                  variant="ghost"
                  aria-label={`Remove: ${ruleText(rule)}`}
                  loading={remove.isPending && remove.variables === rule.id}
                  onClick={() => remove.mutate(rule.id)}
                >
                  <Trash2 aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function AddRule({ space }: { space: Space }) {
  const tables = useTables(space.id);
  const directory = useDirectory(true);
  const add = useAddRule(space.id);
  const [kind, setKind] = useState<RuleKind>("hide_column");
  const [tableId, setTableId] = useState("");
  const [column, setColumn] = useState("");
  const [expression, setExpression] = useState("");
  const [audience, setAudience] = useState<Audience>("viewers");
  const [who, setWho] = useState<"audience" | "person">("audience");
  const [userId, setUserId] = useState("");
  const [shown, setShown] = useState<string | null>(null);

  const list = tables.data ?? [];
  const table = list.find((t) => t.id === tableId);
  const draft: AccessRuleDraft = {
    table_id: tableId,
    kind,
    column: kind === "row_filter" ? null : column || null,
    expression: kind === "row_filter" ? expression : null,
    audience,
    user_id: who === "person" ? userId || null : null,
  };
  const problem = draftProblem(draft, who);
  const error = add.error ? asApiError(add.error) : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    setShown(problem);
    if (problem) return;
    add.mutate(draft, {
      onSuccess: () => {
        setColumn("");
        setExpression("");
      },
    });
  }

  return (
    <Card>
      <CardHeader title="Add a rule" />
      <form onSubmit={submit} className="space-y-4 p-5" noValidate>
        {error && (
          <Notice tone="error" title="Rule not added">
            {error.message}
          </Notice>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <SelectField
              label="What to do"
              value={kind}
              onChange={(event) => setKind(event.target.value as RuleKind)}
              options={KIND_OPTIONS.map(({ value, label }) => ({ value, label }))}
            />
            <p className="text-[12.5px] text-subtle">
              {KIND_OPTIONS.find((k) => k.value === kind)?.help}
            </p>
          </div>
          <SelectField
            label="Table"
            value={tableId}
            onChange={(event) => {
              setTableId(event.target.value);
              setColumn("");
            }}
            options={[
              { value: "", label: tables.isPending ? "Loading…" : "Choose a table" },
              ...list.map((t) => ({ value: t.id, label: t.name })),
            ]}
          />
          {kind === "row_filter" ? (
            <div className="sm:col-span-2">
              <TextField
                label="Rows must meet"
                placeholder="region = 'West'"
                value={expression}
                onChange={(event) => setExpression(event.target.value)}
                hint="Compare this table's columns with values: AND, OR, NOT, =, <>, <, >, IN, BETWEEN, LIKE, IS NULL."
                className="font-mono"
              />
            </div>
          ) : (
            <SelectField
              label="Column"
              value={column}
              disabled={!table}
              onChange={(event) => setColumn(event.target.value)}
              options={[
                { value: "", label: table ? "Choose a column" : "Choose a table first" },
                ...(table?.columns ?? []).map((c) => ({ value: c.name, label: c.name })),
              ]}
            />
          )}
          <SelectField
            label="For"
            value={who === "person" ? "person" : audience}
            onChange={(event) => {
              const value = event.target.value;
              if (value === "person") setWho("person");
              else {
                setWho("audience");
                setAudience(value as Audience);
              }
            }}
            options={[...AUDIENCE_OPTIONS, { value: "person", label: "One person…" }]}
          />
          {who === "person" && (
            <SelectField
              label="Person"
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
              options={[
                { value: "", label: directory.isPending ? "Loading…" : "Choose a person" },
                ...(directory.data ?? []).map((p) => ({
                  value: p.id,
                  label: `${p.full_name} (${p.email})`,
                })),
              ]}
            />
          )}
        </div>
        {shown && (
          <p role="alert" className="text-[13px] text-danger">
            {shown}
          </p>
        )}
        <Button type="submit" variant="primary" loading={add.isPending}>
          Add rule
        </Button>
      </form>
    </Card>
  );
}
