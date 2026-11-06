import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiGet, apiSend, apiUpload } from "../../lib/api";
import { pollInterval } from "./benchmarks";
import { documentsPollInterval } from "./documents";
import type {
  AttachResult,
  AccuracyReport,
  BenchmarkInput,
  BenchmarkItem,
  BenchmarkRun,
  BenchmarkRunDetail,
  GateSettings,
  GateStatus,
  ColumnMeta,
  ColumnUpdate,
  DataLimits,
  DataTable,
  DocumentInfo,
  ExternalTable,
  ExpressionChange,
  ExpressionInput,
  DocumentLimits,
  IndexStatus,
  Join,
  JoinInput,
  KnowledgeInput,
  KnowledgeItem,
  Member,
  Person,
  QueryResult,
  RefreshResult,
  Space,
  SearchResult,
  SpaceRole,
  SqlExpression,
  TableDraft,
  TableMeta,
  ValueMatch,
} from "./types";

const SPACES = ["spaces"] as const;
const space = (id: string) => [...SPACES, id] as const;

export function useSpaces() {
  return useQuery({ queryKey: SPACES, queryFn: () => apiGet<Space[]>("/spaces") });
}

export function useSpace(id: string) {
  return useQuery({ queryKey: space(id), queryFn: () => apiGet<Space>(`/spaces/${id}`) });
}

export function useDataLimits() {
  return useQuery({
    queryKey: ["data-limits"],
    queryFn: () => apiGet<DataLimits>("/spaces/limits"),
    staleTime: Infinity,
  });
}

export function useCreateSpace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; description: string }) =>
      apiSend<Space>("POST", "/spaces", input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SPACES }),
  });
}

export function useUpdateSpace(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (change: {
      name?: string;
      description?: string;
      tags?: string[];
      suggested_questions?: string[];
    }) => apiSend<Space>("PATCH", `/spaces/${id}`, change),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SPACES }),
  });
}

export function useDeleteSpace(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<void>("DELETE", `/spaces/${id}`),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: space(id) });
      return queryClient.invalidateQueries({ queryKey: SPACES, exact: true });
    },
  });
}

// ── Tables ───────────────────────────────────────────────────────────────────

const tables = (spaceId: string) => [...space(spaceId), "tables"] as const;
const metadata = (spaceId: string) => [...space(spaceId), "metadata"] as const;
const joins = (spaceId: string) => [...space(spaceId), "joins"] as const;
const values = (spaceId: string) => [...space(spaceId), "values"] as const;

export function useTables(spaceId: string) {
  return useQuery({
    queryKey: tables(spaceId),
    queryFn: () => apiGet<DataTable[]>(`/spaces/${spaceId}/tables`),
  });
}

export function usePreview(spaceId: string, tableId: string) {
  return useQuery({
    queryKey: [...tables(spaceId), tableId, "preview"],
    queryFn: () => apiGet<QueryResult>(`/spaces/${spaceId}/tables/${tableId}/preview`),
    staleTime: 60_000,
  });
}

/** After the table list changes, the space's table count does too. */
function useTablesChanged(spaceId: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: tables(spaceId) }),
      queryClient.invalidateQueries({ queryKey: metadata(spaceId) }),
      queryClient.invalidateQueries({ queryKey: joins(spaceId) }),
      queryClient.invalidateQueries({ queryKey: values(spaceId) }),
      queryClient.invalidateQueries({ queryKey: [...space(spaceId), "index"] }),
      queryClient.invalidateQueries({ queryKey: SPACES, exact: true }),
      queryClient.invalidateQueries({ queryKey: space(spaceId), exact: true }),
    ]);
}

export function useUploadTable(spaceId: string) {
  const changed = useTablesChanged(spaceId);
  return useMutation({
    mutationFn: ({
      file,
      name,
      onProgress,
      signal,
    }: {
      file: File;
      name?: string;
      onProgress: (fraction: number) => void;
      signal: AbortSignal;
    }) => {
      const form = new FormData();
      form.append("file", file);
      if (name) form.append("name", name);
      return apiUpload<DataTable>(`/spaces/${spaceId}/tables/upload`, form, onProgress, signal);
    },
    meta: { errorToast: "Upload failed" },
    onSuccess: changed,
  });
}

export function useAddDeltaTable(spaceId: string) {
  const changed = useTablesChanged(spaceId);
  return useMutation({
    mutationFn: (input: { path: string; name?: string }) =>
      apiSend<DataTable>("POST", `/spaces/${spaceId}/tables/delta`, input),
    onSuccess: changed,
  });
}

export function useDeleteTable(spaceId: string) {
  const changed = useTablesChanged(spaceId);
  return useMutation({
    mutationFn: (tableId: string) =>
      apiSend<void>("DELETE", `/spaces/${spaceId}/tables/${tableId}`),
    onSuccess: changed,
  });
}

export function useRunQuery(spaceId: string) {
  return useMutation({
    mutationFn: (sql: string) => apiSend<QueryResult>("POST", `/spaces/${spaceId}/query`, { sql }),
  });
}

// ── Members ──────────────────────────────────────────────────────────────────

const members = (spaceId: string) => [...space(spaceId), "members"] as const;

export function useMembers(spaceId: string) {
  return useQuery({
    queryKey: members(spaceId),
    queryFn: () => apiGet<Member[]>(`/spaces/${spaceId}/members`),
  });
}

/** Everyone who can be added to a space (admins and editors only). */
export function useDirectory(enabled: boolean) {
  return useQuery({
    queryKey: ["users", "directory"],
    queryFn: () => apiGet<Person[]>("/users/directory"),
    enabled,
  });
}

function useMembersChanged(spaceId: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: members(spaceId) }),
      queryClient.invalidateQueries({ queryKey: SPACES, exact: true }),
      queryClient.invalidateQueries({ queryKey: space(spaceId), exact: true }),
    ]);
}

export function useSetMember(spaceId: string) {
  const changed = useMembersChanged(spaceId);
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: SpaceRole }) =>
      apiSend<Member>("PUT", `/spaces/${spaceId}/members/${userId}`, { role }),
    onSuccess: changed,
  });
}

export function useRemoveMember(spaceId: string) {
  const changed = useMembersChanged(spaceId);
  return useMutation({
    mutationFn: (userId: string) => apiSend<void>("DELETE", `/spaces/${spaceId}/members/${userId}`),
    onSuccess: changed,
  });
}

// ── Metadata: descriptions, profiles, searchable values, joins ───────────────

export function useMetadata(spaceId: string) {
  return useQuery({
    queryKey: metadata(spaceId),
    queryFn: () => apiGet<TableMeta[]>(`/spaces/${spaceId}/metadata`),
  });
}

/** Editing or re-reading a table changes what the AI knows, and what can be searched. */
function useMetadataChanged(spaceId: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: metadata(spaceId) }),
      queryClient.invalidateQueries({ queryKey: values(spaceId) }),
      queryClient.invalidateQueries({ queryKey: [...space(spaceId), "index"] }),
    ]);
}

export function useProfileTable(spaceId: string) {
  const changed = useMetadataChanged(spaceId);
  return useMutation({
    mutationFn: (tableId: string) =>
      apiSend<TableMeta>("POST", `/spaces/${spaceId}/tables/${tableId}/profile`),
    onSuccess: changed,
  });
}

export function useDraftTable(spaceId: string) {
  return useMutation({
    mutationFn: (tableId: string) =>
      apiSend<TableDraft>("POST", `/spaces/${spaceId}/tables/${tableId}/draft`),
  });
}

export function useSetTableDescription(spaceId: string) {
  const changed = useMetadataChanged(spaceId);
  return useMutation({
    mutationFn: ({ tableId, description }: { tableId: string; description: string }) =>
      apiSend<TableMeta>("PATCH", `/spaces/${spaceId}/tables/${tableId}/metadata`, { description }),
    onSuccess: changed,
  });
}

export function useUpdateColumn(spaceId: string) {
  const changed = useMetadataChanged(spaceId);
  return useMutation({
    mutationFn: ({
      tableId,
      columnId,
      change,
    }: {
      tableId: string;
      columnId: string;
      change: ColumnUpdate;
    }) =>
      apiSend<ColumnMeta>(
        "PATCH",
        `/spaces/${spaceId}/tables/${tableId}/columns/${columnId}`,
        change,
      ),
    onSuccess: changed,
  });
}

export function useValueSearch(spaceId: string, text: string) {
  return useQuery({
    queryKey: [...values(spaceId), text],
    queryFn: () =>
      apiGet<ValueMatch[]>(`/spaces/${spaceId}/values?q=${encodeURIComponent(text)}&limit=10`),
    enabled: text.length > 0,
  });
}

export function useJoins(spaceId: string) {
  return useQuery({
    queryKey: joins(spaceId),
    queryFn: () => apiGet<Join[]>(`/spaces/${spaceId}/joins`),
  });
}

export function useDetectJoins(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<Join[]>("POST", `/spaces/${spaceId}/joins/detect`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: joins(spaceId) }),
  });
}

export function useCreateJoin(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: JoinInput) => apiSend<Join>("POST", `/spaces/${spaceId}/joins`, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: joins(spaceId) }),
  });
}

export function useUpdateJoin(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      joinId,
      change,
    }: {
      joinId: string;
      change: Partial<JoinInput> & { confirmed?: boolean };
    }) => apiSend<Join>("PATCH", `/spaces/${spaceId}/joins/${joinId}`, change),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: joins(spaceId) }),
  });
}

export function useDeleteJoin(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (joinId: string) => apiSend<void>("DELETE", `/spaces/${spaceId}/joins/${joinId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: joins(spaceId) }),
  });
}

// ── Knowledge: instructions, glossary, example SQL, documents, search ────────

const knowledge = (spaceId: string) => [...space(spaceId), "knowledge"] as const;
const documents = (spaceId: string) => [...space(spaceId), "documents"] as const;
const index = (spaceId: string) => [...space(spaceId), "index"] as const;

export function useKnowledge(spaceId: string) {
  return useQuery({
    queryKey: knowledge(spaceId),
    queryFn: () => apiGet<KnowledgeItem[]>(`/spaces/${spaceId}/knowledge`),
  });
}

/** Whatever changes what is searchable also changes the index counts. */
function useKnowledgeChanged(spaceId: string, ...keys: Array<readonly unknown[]>) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all(
      [index(spaceId), ...keys].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    );
}

export function useCreateKnowledge(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, knowledge(spaceId));
  return useMutation({
    mutationFn: (input: KnowledgeInput) =>
      apiSend<KnowledgeItem>("POST", `/spaces/${spaceId}/knowledge`, input),
    onSuccess: changed,
  });
}

export function useUpdateKnowledge(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, knowledge(spaceId));
  return useMutation({
    mutationFn: ({ id, change }: { id: string; change: Partial<KnowledgeInput> }) =>
      apiSend<KnowledgeItem>("PATCH", `/spaces/${spaceId}/knowledge/${id}`, change),
    onSuccess: changed,
  });
}

export function useDeleteKnowledge(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, knowledge(spaceId));
  return useMutation({
    mutationFn: (id: string) => apiSend<void>("DELETE", `/spaces/${spaceId}/knowledge/${id}`),
    onSuccess: changed,
  });
}

export function useDocuments(spaceId: string) {
  return useQuery({
    queryKey: documents(spaceId),
    queryFn: () => apiGet<DocumentInfo[]>(`/spaces/${spaceId}/documents`),
    refetchInterval: (query) => documentsPollInterval(query.state.data),
  });
}

export function useDocumentLimits(spaceId: string) {
  return useQuery({
    queryKey: [...documents(spaceId), "limits"],
    queryFn: () => apiGet<DocumentLimits>(`/spaces/${spaceId}/documents/limits`),
    staleTime: Infinity,
  });
}

export function useUploadDocument(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, documents(spaceId));
  return useMutation({
    mutationFn: ({
      file,
      onProgress,
      signal,
    }: {
      file: File;
      onProgress: (fraction: number) => void;
      signal: AbortSignal;
    }) => {
      const form = new FormData();
      form.append("file", file);
      return apiUpload<DocumentInfo>(`/spaces/${spaceId}/documents`, form, onProgress, signal);
    },
    meta: { errorToast: "Upload failed" },
    onSuccess: changed,
  });
}

export function useDeleteDocument(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, documents(spaceId));
  return useMutation({
    mutationFn: (id: string) => apiSend<void>("DELETE", `/spaces/${spaceId}/documents/${id}`),
    onSuccess: changed,
  });
}

export function useRenameDocument(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, documents(spaceId));
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      apiSend<DocumentInfo>("PATCH", `/spaces/${spaceId}/documents/${id}`, { title }),
    onSuccess: changed,
  });
}

export function useRereadDocument(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, documents(spaceId));
  return useMutation({
    mutationFn: (id: string) =>
      apiSend<DocumentInfo>("POST", `/spaces/${spaceId}/documents/${id}/reread`),
    onSuccess: changed,
  });
}

export function useIndexStatus(spaceId: string) {
  return useQuery({
    queryKey: index(spaceId),
    queryFn: () => apiGet<IndexStatus>(`/spaces/${spaceId}/index`),
  });
}

export function useRebuildIndex(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, documents(spaceId));
  return useMutation({
    mutationFn: () =>
      apiSend<{ added: number; updated: number; removed: number }>(
        "POST",
        `/spaces/${spaceId}/index/rebuild`,
      ),
    onSuccess: changed,
  });
}

export function useSearchTest(spaceId: string) {
  return useMutation({
    mutationFn: (question: string) =>
      apiGet<SearchResult>(`/spaces/${spaceId}/search?q=${encodeURIComponent(question)}`),
  });
}

// ── SQL expressions (business definitions) ───────────────────────────────────

const expressions = (spaceId: string) => [...space(spaceId), "expressions"] as const;

export function useExpressions(spaceId: string) {
  return useQuery({
    queryKey: expressions(spaceId),
    queryFn: () => apiGet<SqlExpression[]>(`/spaces/${spaceId}/expressions`),
  });
}

export function useCreateExpression(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, expressions(spaceId));
  return useMutation({
    mutationFn: (input: ExpressionInput) =>
      apiSend<SqlExpression>("POST", `/spaces/${spaceId}/expressions`, input),
    onSuccess: changed,
  });
}

export function useUpdateExpression(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, expressions(spaceId));
  return useMutation({
    mutationFn: ({ id, change }: { id: string; change: ExpressionChange }) =>
      apiSend<SqlExpression>("PATCH", `/spaces/${spaceId}/expressions/${id}`, change),
    onSuccess: changed,
  });
}

export function useDeleteExpression(spaceId: string) {
  const changed = useKnowledgeChanged(spaceId, expressions(spaceId));
  return useMutation({
    mutationFn: (id: string) => apiSend<void>("DELETE", `/spaces/${spaceId}/expressions/${id}`),
    onSuccess: changed,
  });
}

// ── Tables of an external database (admins) ──────────────────────────────────

export function useExternalSchema(connectionId: string, spaceId: string) {
  return useQuery({
    queryKey: ["connections", connectionId, "schema", spaceId],
    queryFn: () =>
      apiGet<ExternalTable[]>(`/connections/${connectionId}/schema?space_id=${spaceId}`),
    enabled: connectionId !== "",
    staleTime: 0,
    retry: false,
  });
}

export function useAttachTables(spaceId: string) {
  const changed = useTablesChanged(spaceId);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      connection_id: string;
      tables: Array<{ schema: string; name: string }>;
    }) => apiSend<AttachResult>("POST", `/spaces/${spaceId}/tables/external`, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      await changed();
    },
  });
}

/** Without `apply` this only reports what a refresh would change. */
export function useRefreshTables(spaceId: string) {
  const changed = useTablesChanged(spaceId);
  return useMutation({
    mutationFn: (apply: boolean) =>
      apiSend<RefreshResult>(
        "POST",
        `/spaces/${spaceId}/tables/external/refresh?apply=${apply ? "true" : "false"}`,
      ),
    onSuccess: (result) => (result.applied ? changed() : undefined),
  });
}

// ── Benchmarks (editors) ─────────────────────────────────────────────────────

const benchmarks = (spaceId: string) => [...space(spaceId), "benchmarks"] as const;

export function useBenchmarks(spaceId: string) {
  return useQuery({
    queryKey: benchmarks(spaceId),
    queryFn: () => apiGet<BenchmarkItem[]>(`/spaces/${spaceId}/benchmarks`),
  });
}

export function useCreateBenchmark(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: BenchmarkInput) =>
      apiSend<BenchmarkItem>("POST", `/spaces/${spaceId}/benchmarks`, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: benchmarks(spaceId) }),
  });
}

export function useDeleteBenchmark(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiSend<void>("DELETE", `/spaces/${spaceId}/benchmarks/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: benchmarks(spaceId) }),
  });
}

/** The runs, newest first. Asked again every moment while the latest one is still going. */
export function useBenchmarkRuns(spaceId: string) {
  return useQuery({
    queryKey: [...benchmarks(spaceId), "runs"],
    queryFn: () => apiGet<BenchmarkRun[]>(`/spaces/${spaceId}/benchmarks/runs`),
    refetchInterval: (query) => pollInterval(query.state.data?.[0]),
  });
}

/** One run with its results. Asked again every moment while the run is still going. */
export function useBenchmarkRun(spaceId: string, runId: string | null) {
  return useQuery({
    queryKey: [...benchmarks(spaceId), "runs", runId],
    queryFn: () => apiGet<BenchmarkRunDetail>(`/spaces/${spaceId}/benchmarks/runs/${runId}`),
    enabled: runId !== null,
    refetchInterval: (query) => pollInterval(query.state.data),
  });
}

export function useStartBenchmarkRun(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiSend<BenchmarkRun>("POST", `/spaces/${spaceId}/benchmarks/runs`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: benchmarks(spaceId) }),
  });
}

/** `latestStatus` is in the key so the score is fetched again when a run finishes. */
export function useAccuracy(spaceId: string, latestStatus?: string) {
  return useQuery({
    queryKey: [...benchmarks(spaceId), "accuracy", latestStatus],
    queryFn: () => apiGet<AccuracyReport>(`/spaces/${spaceId}/benchmarks/accuracy`),
  });
}

export function useUpdateGate(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (settings: GateSettings) =>
      apiSend<GateStatus>("PUT", `/spaces/${spaceId}/benchmarks/gate`, settings),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: benchmarks(spaceId) }),
  });
}

export function useAcceptBaseline(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      apiSend<GateStatus>("PUT", `/spaces/${spaceId}/benchmarks/gate/baseline`, {
        run_id: runId,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: benchmarks(spaceId) }),
  });
}
