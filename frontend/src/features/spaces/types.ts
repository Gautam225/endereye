export type SpaceRole = "editor" | "viewer";

export interface Space {
  id: string;
  name: string;
  description: string;
  /** The space behind a person's general chat: no tables, never listed. */
  is_personal?: boolean;
  tags: string[];
  /** Questions offered when a conversation starts. */
  suggested_questions: string[];
  /** Who created the space. */
  owner_name: string | null;
  /** Admins always act as editors. */
  my_role: SpaceRole;
  table_count: number;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface Member {
  user_id: string;
  full_name: string;
  email: string;
  role: SpaceRole;
  is_active: boolean;
}

export interface Person {
  id: string;
  full_name: string;
  email: string;
}

export interface Column {
  name: string;
  type: string;
}

export interface DataTable {
  id: string;
  name: string;
  source_type: "upload" | "delta_path" | "external";
  /** The uploaded file's name, the Delta folder, or "schema.table" in an external database. */
  source_ref: string;
  connection_id: string | null;
  columns: Column[];
  row_count: number;
  size_bytes: number | null;
  delta_version: number | null;
  description: string;
  profiled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface QueryResult {
  columns: Column[];
  rows: unknown[][];
  row_count: number;
  /** More rows existed than were returned. */
  truncated: boolean;
  elapsed_ms: number;
}

export interface DataLimits {
  max_upload_mb: number;
  /** Extensions, e.g. ".csv". */
  file_types: string[];
  query_max_rows: number;
  query_timeout_seconds: number;
}

// ── What the AI knows about the data ─────────────────────────────────────────

export type Relationship = "many_to_one" | "one_to_many" | "one_to_one";

export interface ColumnStats {
  null_count: number;
  null_pct: number;
  /** Null for nested types. */
  distinct_count: number | null;
  min: string | null;
  max: string | null;
  top_values: Array<{ value: string; count: number }>;
  /** Short text with at most 1,024 distinct values. */
  searchable: boolean;
}

export interface ColumnMeta {
  id: string;
  name: string;
  type: string;
  position: number;
  description: string;
  synonyms: string[];
  /** Left out of what the AI sees. Data and permissions are unchanged. */
  hidden: boolean;
  /** Sample and common values are shown to the AI. */
  share_values: boolean;
  /** The column's distinct values are searchable. Needs share_values. */
  entity_matching: boolean;
  indexed_values: number;
  stats: ColumnStats | null;
}

export interface TableMeta {
  id: string;
  name: string;
  description: string;
  row_count: number;
  profiled_at: string | null;
  /** A Delta table has a newer version than the one profiled. */
  stale: boolean;
  columns: ColumnMeta[];
}

export interface ColumnUpdate {
  description?: string;
  synonyms?: string[];
  hidden?: boolean;
  share_values?: boolean;
  entity_matching?: boolean;
}

export interface TableDraft {
  description: string;
  columns: Array<{ name: string; description: string; synonyms: string[] }>;
}

export interface Join {
  id: string;
  left_table_id: string;
  left_table: string;
  left_column: string;
  right_table_id: string;
  right_table: string;
  right_column: string;
  relationship: Relationship;
  source: "detected" | "manual" | "foreign_key";
  confirmed: boolean;
}

export interface JoinInput {
  left_table_id: string;
  left_column: string;
  right_table_id: string;
  right_column: string;
  relationship: Relationship;
}

export interface ValueMatch {
  table: string;
  column: string;
  value: string;
  score: number;
}

// ── Knowledge: instructions, glossary, example SQL, documents, search ────────

export type KnowledgeKind = "instruction" | "glossary" | "example_sql" | "clarification";

export type ExpressionType = "measure" | "filter" | "dimension";

/** A business definition written as SQL, applied exactly as written. */
export interface SqlExpression {
  id: string;
  name: string;
  type: ExpressionType;
  expression: string;
  table_name: string | null;
  description: string;
  synonyms: string[];
  /** Filters only: added to every query that uses the table. */
  is_default: boolean;
  /** Who answers for this definition. */
  owner_id: string | null;
  owner_name: string | null;
  /** Goes up with every change to the definition. */
  version: number;
  tests_total: number;
  /** Tests that failed, or could not run, at their last check. */
  tests_failing: number;
  created_at: string;
  updated_at: string;
}

/** One saved state of a definition. */
export interface ExpressionVersion {
  version: number;
  name: string;
  type: ExpressionType;
  expression: string;
  table_name: string | null;
  description: string;
  synonyms: string[];
  is_default: boolean;
  note: string;
  changed_by_name: string | null;
  changed_at: string;
}

/** A check that a definition still gives the right number. */
export interface ExpressionTest {
  id: string;
  expression_id: string;
  name: string;
  where_sql: string | null;
  expected: number;
  tolerance: number;
  last_status: "pass" | "fail" | "error" | null;
  last_value: number | null;
  last_detail: string;
  last_checked_at: string | null;
  last_version: number | null;
}

export interface TestRun {
  passed: number;
  failed: number;
  tests: ExpressionTest[];
}

export interface ExpressionChange extends Partial<ExpressionInput> {
  owner_id?: string;
  /** Why it changed: kept with the new version. */
  note?: string;
  /** Save even though a test of the definition now fails. */
  accept_failing_tests?: boolean;
}

export interface ExpressionInput {
  name: string;
  type: ExpressionType;
  expression: string;
  table_name: string | null;
  description: string;
  synonyms: string[];
  is_default: boolean;
}

export interface KnowledgeItem {
  id: string;
  kind: KnowledgeKind;
  /** The question (example SQL), the term (glossary), or an optional short name. */
  title: string;
  /** The rule, the definition, or the SQL. */
  body: string;
  trusted: boolean;
  note: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeInput {
  kind: KnowledgeKind;
  title: string;
  body: string;
  trusted?: boolean;
  note?: string;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  title: string;
  /** What to type after @ to point at the document. */
  mention: string;
  /** Set for a file added in one chat; null for a space document. */
  conversation_id: string | null;
  size_bytes: number;
  status: "processing" | "ready" | "failed";
  error: string | null;
  chunk_count: number;
  /** Pages (or slides) the file has, where the format has them. */
  page_count: number | null;
  /** Pages read from a picture with OCR: the text may hold mistakes. */
  ocr_pages: number[];
  /** Pages that are pictures nothing could be read from. */
  unread_pages: number[];
  parser: string;
  created_at: string;
  uploaded_by: string | null;
}

export interface DocumentLimits {
  file_types: string[];
  max_upload_mb: number;
}

export interface SearchHit {
  id: number;
  source_type: string;
  header: string;
  snippet: string;
  vector_rank: number | null;
  vector_distance: number | null;
  bm25_rank: number | null;
  bm25_score: number | null;
  fused_rank: number | null;
  rerank_score: number | null;
  /** Set when the AI would be shown it. */
  final_rank: number | null;
}

export interface SearchPassage {
  header: string;
  text: string;
  source_type: string;
  score: number;
  chunk_ids: number[];
  meta: Record<string, unknown>;
}

export interface SearchResult {
  query: string;
  hits: SearchHit[];
  passages: SearchPassage[];
  timings_ms: Record<string, number>;
}

export interface IndexStatus {
  chunks: Record<string, number>;
  documents: number;
  failed_documents: number;
  embedding_model: string;
  rerank_model: string;
  chunk_tokens: number;
  chunk_overlap_tokens: number;
  document_parser: string;
}

// ── Tables of an external database ───────────────────────────────────────────

export interface ExternalColumn {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
  comment: string;
}

export interface ExternalForeignKey {
  name: string;
  columns: string[];
  ref_schema: string;
  ref_table: string;
  ref_columns: string[];
  /** A join is one column to one column; a key over several is listed but not stored. */
  supported: boolean;
}

/** A table or view the connection's login can read. */
export interface ExternalTable {
  schema: string;
  name: string;
  kind: string;
  comment: string;
  estimated_rows: number | null;
  columns: ExternalColumn[];
  foreign_keys: ExternalForeignKey[];
  attached_here: boolean;
}

export interface AttachResult {
  tables: DataTable[];
  joins_created: number;
  skipped_foreign_keys: string[];
}

export interface TableChange {
  name: string;
  ref: string;
  status: "unchanged" | "changed" | "missing";
  added_columns: string[];
  removed_columns: string[];
  type_changes: Array<{ column: string; from_type: string; to_type: string }>;
}

export interface RefreshResult {
  applied: boolean;
  tables: TableChange[];
  joins_added: number;
  joins_removed: number;
  skipped_foreign_keys: string[];
}

// ── Benchmarks ───────────────────────────────────────────────────────────────

export type Outcome = "correct" | "incorrect" | "failed" | "not_a_query" | "reference_error";

/** A question with the SQL that is known to answer it correctly. */
export interface BenchmarkItem {
  id: string;
  question: string;
  expected_sql: string;
  /** The order of the rows is part of the right answer (a ranking). */
  ordered: boolean;
  created_at: string;
  updated_at: string;
  last_outcome: Outcome | null;
}

export interface BenchmarkRun {
  id: string;
  status: "running" | "finished" | "failed";
  total: number;
  done: number;
  correct: number;
  incorrect: number;
  failed: number;
  reference_errors: number;
  accuracy: number | null;
  error: string;
  started_at: string;
  finished_at: string | null;
  started_by_name: string | null;
}

export interface BenchmarkResult {
  id: string;
  position: number;
  question: string;
  expected_sql: string;
  generated_sql: string | null;
  outcome: Outcome;
  detail: string;
  attempts: number;
  expected_rows: number | null;
  actual_rows: number | null;
  duration_ms: number;
}

export interface BenchmarkRunDetail extends BenchmarkRun {
  results: BenchmarkResult[];
}

export interface BenchmarkInput {
  question: string;
  expected_sql: string;
  ordered: boolean;
}

export type GateResult = "passed" | "failed" | "skipped" | "no_run";

export interface GateSettings {
  enabled: boolean;
  max_drop: number;
  min_accuracy: number | null;
}

export interface GateStatus extends GateSettings {
  baseline_run_id: string | null;
  baseline_accuracy: number | null;
  latest_run_id: string | null;
  latest_accuracy: number | null;
  result: GateResult;
  reasons: string[];
}

export interface AccuracyPoint {
  run_id: string;
  at: string;
  accuracy: number | null;
  correct: number;
  judged: number;
}

export interface AccuracyReport {
  points: AccuracyPoint[];
  gate: GateStatus;
}
