// Mirrors backend/app/schemas/health.py and backend/app/schemas/llm.py.

export interface CheckResult {
  status: "ok" | "error";
  version: string | null;
  latency_ms: number | null;
  detail: string | null;
}

export interface Health {
  status: "ok" | "degraded";
  app: string;
  version: string;
  environment: string;
  checks: Record<string, CheckResult>;
}

export interface KeyStatus {
  index: number;
  masked: string;
  state: "ready" | "resting" | "disabled";
  rest_seconds: number;
  model_rests: Record<string, number>;
  reason: string | null;
  last_error: string | null;
  successes: number;
  failures: number;
  last_used_at: string | null;
}

export type Tier = "smart" | "fast";

export interface ModelStatus {
  id: string;
  tiers: Tier[];
  check: "ok" | "missing" | "unchecked" | "error";
  detail: string | null;
}

export interface ProviderStatus {
  name: string;
  role: "primary" | "fallback";
  configured: boolean;
  max_prompt_tokens: number | null;
  keys: KeyStatus[];
  models: ModelStatus[];
}

export interface RecentCalls {
  window_hours: number;
  total: number;
  by_outcome: Record<string, number>;
  by_provider: Record<string, number>;
}

export interface LlmStatus {
  providers: ProviderStatus[];
  recent_calls: RecentCalls | null;
}
