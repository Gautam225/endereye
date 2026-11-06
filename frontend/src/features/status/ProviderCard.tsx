import { KeyRound } from "lucide-react";

import { Card, CardHeader } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/Notice";
import { Badge, StatusLabel, type Tone } from "../../components/ui/Status";
import { providerLabel, shortDuration, timeAgo } from "../../lib/format";
import type { KeyStatus, ModelStatus, ProviderStatus } from "./types";

const ENV_PREFIX: Record<string, string> = {
  openrouter: "OPENROUTER_API_KEY_",
  groq: "GROQ_API_KEY_",
};

export function ProviderCard({ provider }: { provider: ProviderStatus }) {
  const name = providerLabel[provider.name] ?? provider.name;
  const ready = provider.keys.filter((key) => key.state === "ready").length;

  return (
    <Card>
      <CardHeader
        title={
          <>
            {name}
            <Badge tone={provider.role === "primary" ? "accent" : "neutral"}>
              {provider.role === "primary" ? "Primary" : "Fallback"}
            </Badge>
          </>
        }
        description={
          provider.role === "primary"
            ? "Tried first. Keys take turns so the load spreads evenly."
            : "Used only when every primary key is busy or failing."
        }
        aside={
          provider.configured && (
            <span className="text-[13px] text-muted">
              {ready} of {provider.keys.length} keys ready
            </span>
          )
        }
      />

      {provider.configured ? (
        <ul className="divide-y divide-border">
          {provider.keys.map((key) => (
            <KeyRow key={key.index} apiKey={key} />
          ))}
        </ul>
      ) : (
        <EmptyState icon={KeyRound} title="No keys yet">
          Add <code className="font-mono text-fg">{ENV_PREFIX[provider.name]}1</code> (up to{" "}
          <code className="font-mono text-fg">_4</code> or more) to <code>.env</code>, then restart
          the backend.
        </EmptyState>
      )}

      <div className="border-t border-border px-5 py-4">
        <p className="mb-2.5 text-[13px] font-medium text-muted">Models</p>
        <ul className="space-y-2">
          {provider.models.map((model) => (
            <ModelRow key={model.id} model={model} />
          ))}
        </ul>
      </div>
    </Card>
  );
}

function keyState(key: KeyStatus): { tone: Tone; label: string } {
  if (key.state === "disabled") return { tone: "error", label: "Disabled" };
  if (key.state === "resting") {
    const wait = Math.max(key.rest_seconds, ...Object.values(key.model_rests));
    return { tone: "warn", label: `Resting · ${shortDuration(wait)}` };
  }
  return { tone: "ok", label: "Ready" };
}

function KeyRow({ apiKey }: { apiKey: KeyStatus }) {
  const { tone, label } = keyState(apiKey);
  const partialRests = apiKey.state === "ready" ? Object.entries(apiKey.model_rests) : [];

  return (
    <li className="px-5 py-3">
      <div className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-1 sm:grid-cols-[3rem_11rem_1fr_auto]">
        <span className="font-mono text-[13px] text-muted">#{apiKey.index}</span>
        <span className="truncate font-mono text-[13px]">{apiKey.masked}</span>
        <StatusLabel tone={tone} className="col-start-2 sm:col-start-auto">
          {label}
        </StatusLabel>
        <span className="col-start-2 text-[13px] text-subtle tabular-nums sm:col-start-auto sm:text-right">
          {apiKey.successes} ok · {apiKey.failures} failed · used {timeAgo(apiKey.last_used_at)}
        </span>
      </div>
      {apiKey.reason && <p className="mt-2 text-[13px] text-muted sm:pl-16">{apiKey.reason}</p>}
      {partialRests.length > 0 && (
        <p className="mt-2 text-[13px] text-muted sm:pl-16">
          Rate-limited on{" "}
          {partialRests.map(([model, seconds], i) => (
            <span key={model}>
              {i > 0 && ", "}
              <code className="font-mono">{model}</code> for {shortDuration(seconds)}
            </span>
          ))}
          ; other models still use this key.
        </p>
      )}
    </li>
  );
}

const MODEL_CHECK: Record<ModelStatus["check"], { tone: Tone; label: string }> = {
  ok: { tone: "ok", label: "Available" },
  missing: { tone: "error", label: "Not offered" },
  unchecked: { tone: "neutral", label: "Not checked" },
  error: { tone: "warn", label: "Check failed" },
};

function ModelRow({ model }: { model: ModelStatus }) {
  const { tone, label } = MODEL_CHECK[model.check];
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <code className="min-w-0 truncate font-mono text-[13px]">{model.id}</code>
      <span className="flex gap-1">
        {model.tiers.map((tier) => (
          <Badge key={tier}>{tier === "smart" ? "Smart" : "Fast"}</Badge>
        ))}
      </span>
      <StatusLabel tone={tone} className="ml-auto">
        <span title={model.detail ?? undefined}>{label}</span>
      </StatusLabel>
      {(model.check === "missing" || model.check === "error") && model.detail && (
        <p className="w-full text-[12.5px] text-subtle">{model.detail}</p>
      )}
    </li>
  );
}
