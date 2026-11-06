import { Boxes, Clock, Plus, Table2, UsersRound } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { PageHeader } from "../../components/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { plural, timeAgo } from "../../lib/format";
import { useCreateSpace, useSpaces } from "./queries";

const EASE = [0.16, 1, 0.3, 1] as const;

export function SpacesPage() {
  const spaces = useSpaces();
  const { hasRole } = useAuth();
  const canCreate = hasRole("admin", "editor");
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PageHeader
        title="Spaces"
        description="A space is a set of tables about one subject, and the people who can ask about them."
        actions={
          canCreate &&
          !adding && (
            <Button variant="primary" onClick={() => setAdding(true)}>
              <Plus aria-hidden />
              New space
            </Button>
          )
        }
      />

      <div className="space-y-5">
        <AnimatePresence initial={false}>
          {adding && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25, ease: EASE }}
              className="overflow-hidden"
            >
              <NewSpaceForm onCancel={() => setAdding(false)} />
            </motion.div>
          )}
        </AnimatePresence>

        {spaces.isPending ? (
          <div className="grid gap-4 sm:grid-cols-2">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-32" />
            ))}
          </div>
        ) : spaces.isError ? (
          <Notice tone="error" title="Could not load spaces">
            {spaces.error.message}
          </Notice>
        ) : spaces.data.length === 0 ? (
          <Card>
            <EmptyState icon={Boxes} title="No spaces yet">
              {canCreate
                ? "Create one, then upload files or add Delta tables to it."
                : "Ask an editor to add you to a space."}
            </EmptyState>
          </Card>
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2">
            {spaces.data.map((space) => (
              <li key={space.id}>
                <Link
                  to={`/spaces/${space.id}`}
                  className="group flex h-full flex-col rounded-xl border border-border bg-surface p-5 shadow-card transition-colors duration-150 hover:border-border-strong hover:bg-surface-2/40 focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none"
                >
                  <div className="flex items-start gap-3.5">
                    <span
                      aria-hidden
                      className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent"
                    >
                      <Boxes className="size-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-3">
                        <h2 className="min-w-0 truncate text-[15px] font-semibold">{space.name}</h2>
                        <Badge tone={space.my_role === "editor" ? "accent" : "neutral"}>
                          {space.my_role === "editor" ? "Editor" : "Viewer"}
                        </Badge>
                      </div>
                      <p className="mt-1 line-clamp-2 min-h-10 text-[13px] leading-5 text-muted">
                        {space.description || "No description."}
                      </p>
                    </div>
                  </div>
                  <div className="mt-4 flex items-center gap-4 border-t border-border pt-3.5 text-[12.5px] text-subtle">
                    <span className="inline-flex items-center gap-1.5">
                      <Table2 aria-hidden className="size-3.5" />
                      {plural(space.table_count, "table")}
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <UsersRound aria-hidden className="size-3.5" />
                      {plural(space.member_count, "member")}
                    </span>
                    <span className="ml-auto inline-flex items-center gap-1.5">
                      <Clock aria-hidden className="size-3.5" />
                      {timeAgo(space.updated_at)}
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function NewSpaceForm({ onCancel }: { onCancel: () => void }) {
  const create = useCreateSpace();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [touched, setTouched] = useState(false);
  const error = create.error ? asApiError(create.error) : null;
  const nameProblem = name.trim() ? undefined : "Give the space a name.";

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (nameProblem) return;
    create.mutate(
      { name: name.trim(), description: description.trim() },
      { onSuccess: (space) => void navigate(`/spaces/${space.id}`) },
    );
  }

  return (
    <Card>
      <CardHeader
        title="New space"
        description="You become its editor. Add data and people on the next page."
      />
      <form onSubmit={submit} noValidate className="space-y-4 p-5">
        {error && error.code !== "validation_error" && (
          <Notice tone="error" title="Space not created">
            {error.message}
          </Notice>
        )}
        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
          <TextField
            label="Name"
            placeholder="Sales"
            maxLength={80}
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            error={(touched ? nameProblem : undefined) ?? error?.fieldErrors.name}
          />
          <TextField
            label="Description (optional)"
            placeholder="Orders and revenue by region, 2024 onwards"
            maxLength={500}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            error={error?.fieldErrors.description}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Create space
          </Button>
        </div>
      </form>
    </Card>
  );
}
