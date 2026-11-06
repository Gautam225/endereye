export type MessageStatus =
  "running" | "ok" | "empty" | "answer" | "clarify" | "declined" | "failed" | "cancelled";

export type ChartType = "bar" | "line" | "area" | "pie" | "scatter" | "kpi";

/**
 * One chart of a result that has several. Either one analysis of a result that stacks them (the
 * rows where `facet` equals `value`), or, when there is no facet, one kind of figure with its own
 * axis (`y`): an average, a count and a total are never drawn together.
 */
export interface ChartPanel {
  value?: string;
  y?: string[];
  title: string;
  type: ChartType;
  /** "value": the bars go in order, largest first. */
  sort?: "value" | null;
  /** A plain sentence about what this chart shows. */
  note?: string;
}

/** An overall figure (an average of all the rows, a count of distinct values), from the database. */
export interface ChartTotal {
  name: string;
  /** count, sum, avg, min, max, ratio or other. */
  kind: string;
  value: number;
}

export interface ChartSpec {
  type: ChartType;
  x: string | null;
  y: string[];
  series: string | null;
  title: string;
  /** Only a preview of the rows is stored, so the chart shows the first rows. */
  partial?: boolean;
  /** The column that names the analysis when a result stacks several; each gets its own chart. */
  facet?: string | null;
  panels?: ChartPanel[];
  /** What the x axis shows, when the column's own name says nothing (a stacked analysis). */
  xLabel?: string | null;
  /** Bars lie down (the names on the left) when there are many categories or the names are long. */
  orientation?: "horizontal" | null;
  /** "value": the bars go in order, largest first (when the query did not sort them itself). */
  sort?: "value" | null;
  /** Measures that got no chart (more than the limit); they are in the Table. */
  omitted?: string[];
  /** Overall figures to show above the charts. */
  totals?: ChartTotal[];
  /** Which chart of several this is: each gets its own color. */
  colorIndex?: number;
  /** A plain sentence about what the chart shows. */
  note?: string;
}

export interface ResultColumn {
  name: string;
  type: string;
}

/** A chart of numbers found in a document (each number was checked against the document). */
export interface Figure {
  kind: "chart";
  type: "bar" | "line" | "area" | "pie";
  title: string;
  x_label: string;
  y_label: string;
  labels: string[];
  series: Array<{ name: string; values: Array<number | null> }>;
  key_points: string[];
}

/** A line of the thought process shown while an answer is written. */
export interface Thought {
  kind: "step" | "plan" | "note";
  text: string;
}

/** A document or table pointed at with @name in a question. */
export interface Mention {
  id: string;
  name: string;
  /** Absent on questions saved before tables could be mentioned: those are documents. */
  kind?: "document" | "table";
}

/** A passage of a document that an answer rests on. Its tag ("S1") is written in the answer. */
export interface Citation {
  tag: string;
  /** Null for a passage read before documents were tracked: it can be shown but not opened. */
  document_id: string | null;
  title: string;
  /** The page or slide; null for a format without pages (Word, text). */
  page: number | null;
  section: string | null;
  text: string;
  /** False when the answer did not cite it: it was found, not used. */
  cited: boolean;
  /** Read from a picture (OCR), so it may hold mistakes. Absent on older answers. */
  ocr?: boolean;
}

export interface Source {
  type: string;
  header: string;
  /** How many passages of it were used; absent on answers saved before this was counted. */
  passages?: number;
}

/** One analysis of a deep answer: its own query, rows, chart and plain-words summary. */
export interface Step {
  index: number;
  title: string;
  question: string;
  sql: string | null;
  status: "ok" | "empty" | "failed";
  error?: string;
  summary: string;
  columns: ResultColumn[] | null;
  rows: unknown[][] | null;
  row_count: number;
  truncated: boolean;
  chart: ChartSpec | null;
  attempts: number;
  assumptions: string[];
}

/** One question and everything the assistant did about it, as saved by the server. */
export interface ChatMessage {
  id: string;
  seq: number;
  question: string;
  standalone_question: string | null;
  status: MessageStatus;
  sql: string | null;
  trusted: boolean;
  answer: string | null;
  assumptions: string[];
  columns: ResultColumn[] | null;
  rows: unknown[][] | null;
  row_count: number | null;
  truncated: boolean;
  sources: Source[];
  citations: Citation[];
  chart: ChartSpec | null;
  suggestions: string[];
  /** The answers offered with a question the assistant asked. */
  options: string[];
  mode?: "quick" | "standard" | "deep";
  /** The separate analyses of a deep answer (empty otherwise). */
  steps?: Step[];
  mentions: Mention[];
  thoughts: Thought[];
  figures: Figure[];
  feedback: "up" | "down" | null;
  feedback_comment: string | null;
  error_code: string | null;
  error: string | null;
  attempts: number;
  timings: Record<string, number>;
  models: string[];
  created_at: string;
  finished_at: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  /** Pinned chats stay at the top of the list. */
  pinned: boolean;
  /** The other members of the space can read it. */
  shared?: boolean;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
  /** False for a chat another member shared: it can be read and branched, not changed. */
  mine?: boolean;
  owner_name?: string | null;
}

/** Someone a chat is shared with. */
export interface SharePerson {
  id: string;
  full_name: string;
  email: string;
  /** When they first opened it; null while they have not. */
  seen_at: string | null;
}

export interface Shares {
  people: SharePerson[];
  /** Also open to every member of the space (the older kind of sharing). */
  everyone: boolean;
}

/** A chat someone shared with you, from any space. */
export interface InboxItem {
  id: string;
  space_id: string;
  title: string;
  owner_name: string;
  space_name: string;
  personal: boolean;
  shared_at: string;
  updated_at: string;
  unread: boolean;
}

/** A shared chat opened for reading. */
export interface SharedChat extends ConversationDetail {
  space_id: string;
  space_name: string;
  personal: boolean;
}

/** A chat another member of the space shared. */
export interface SharedConversation {
  id: string;
  title: string;
  owner_name: string;
  updated_at: string;
}

export interface DiscoverHit {
  type: "table" | "column" | "glossary" | "document" | "example_sql";
  title: string;
  snippet: string;
}

/** What is known about the answer being written right now. */
export interface LiveTurn {
  question: string;
  /** The turn this one replaces (an edited question), so the old one can be hidden. */
  replaceSeq: number | null;
  messageId: string | null;
  running: boolean;
  stage: string | null;
  stageLabel: string | null;
  doneStages: string[];
  sql: string | null;
  attempt: number;
  result: {
    columns: ResultColumn[];
    rows: unknown[][];
    row_count: number;
    truncated: boolean;
    elapsed_ms: number;
  } | null;
  answer: string | null;
  chart: ChartSpec | null;
  suggestions: string[];
  options: string[];
  steps: Step[];
  thoughts: Thought[];
  figures: Figure[];
  mentions: Mention[];
  error: { code: string; message: string; detail?: string } | null;
  finished: ChatMessage | null;
}
