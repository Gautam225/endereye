import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend } from "../../lib/api";
import type { ExpressionTest, ExpressionVersion, TestRun } from "./types";

/** Hooks for the history and tests of a shared definition (a "metric"). */

const base = (spaceId: string, id: string) => `/spaces/${spaceId}/expressions/${id}`;
const listKey = (spaceId: string) => ["spaces", spaceId, "expressions"] as const;
const detailKey = (spaceId: string, id: string) => [...listKey(spaceId), id] as const;

export function useExpressionVersions(spaceId: string, id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...detailKey(spaceId, id), "versions"],
    queryFn: () => apiGet<ExpressionVersion[]>(`${base(spaceId, id)}/versions`),
    enabled,
  });
}

export function useExpressionTests(spaceId: string, id: string, enabled: boolean) {
  return useQuery({
    queryKey: [...detailKey(spaceId, id), "tests"],
    queryFn: () => apiGet<ExpressionTest[]>(`${base(spaceId, id)}/tests`),
    enabled,
  });
}

/** Everything about one definition (and the list's counts) is read again after a change. */
function useRefreshing<TVariables, TResult>(
  spaceId: string,
  run: (variables: TVariables) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listKey(spaceId) }),
  });
}

export function useRestoreVersion(spaceId: string, id: string) {
  return useRefreshing(
    spaceId,
    ({ version, acceptFailing }: { version: number; acceptFailing: boolean }) =>
      apiSend<unknown>("POST", `${base(spaceId, id)}/versions/${version}/restore`, {
        accept_failing_tests: acceptFailing,
      }),
  );
}

export interface TestInput {
  name: string;
  where_sql: string | null;
  expected: number;
  tolerance: number;
}

export function useCreateTest(spaceId: string, id: string) {
  return useRefreshing(spaceId, (input: TestInput) =>
    apiSend<ExpressionTest>("POST", `${base(spaceId, id)}/tests`, input),
  );
}

export function useDeleteTest(spaceId: string, id: string) {
  return useRefreshing(spaceId, (testId: string) =>
    apiSend<void>("DELETE", `${base(spaceId, id)}/tests/${testId}`),
  );
}

export function useRunTests(spaceId: string, id: string) {
  return useRefreshing(spaceId, () => apiSend<TestRun>("POST", `${base(spaceId, id)}/tests/run`));
}

/** "Got 59, expected 60" and the like are stored as words; this is the short label. */
export function testLabel(test: Pick<ExpressionTest, "last_status">): string {
  if (test.last_status === "pass") return "Passes";
  if (test.last_status === "fail") return "Fails";
  if (test.last_status === "error") return "Can't run";
  return "Not run yet";
}
