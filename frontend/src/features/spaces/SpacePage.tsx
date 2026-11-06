import {
  ArrowLeft,
  BookOpen,
  Boxes,
  Database,
  FileText,
  MessageSquare,
  SearchX,
  Settings,
  ShieldCheck,
  SquareTerminal,
  Tags,
  Target,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useId, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { FadeSwitch } from "../../components/FadeSwitch";

import { PageHeader } from "../../components/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { BareTextArea, TextField } from "../../components/ui/Field";
import { EmptyState, Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { ApiError, asApiError } from "../../lib/api";
import { plural } from "../../lib/format";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/cn";
import { AccessTab } from "./AccessTab";
import { BenchmarksTab } from "./BenchmarksTab";
import { DataTab } from "./DataTab";
import { DocumentsTab } from "./DocumentsTab";
import { KnowledgeTab } from "./KnowledgeTab";
import { MembersTab } from "./MembersTab";
import { parseSynonyms } from "./metadata";
import { MetadataTab } from "./MetadataTab";
import { useDeleteSpace, useSpace, useUpdateSpace } from "./queries";
import { SearchTester } from "./SearchTester";
import { SqlTab } from "./SqlTab";
import type { Space } from "./types";

type TabId =
  | "data"
  | "knowledge"
  | "docs"
  | "library"
  | "sql"
  | "benchmarks"
  | "access"
  | "members"
  | "settings";

interface Section {
  id: TabId;
  label: string;
  icon: LucideIcon;
  /** One plain sentence under the section's name, so nobody has to guess what it is for. */
  about: string;
  editorsOnly?: boolean;
  adminsOnly?: boolean;
}

/** The nine sections, in three groups by what a person is doing: bringing data in, teaching the
 * AI about it, and looking after the space. (The ids stay as they were: links use them.) */
const GROUPS: Array<{ title: string; sections: Section[] }> = [
  {
    title: "Data",
    sections: [
      {
        id: "data",
        label: "Tables",
        icon: Database,
        about: "The tables people can ask about. Add a file, a Delta folder or a database table.",
      },
      {
        id: "library",
        label: "Documents",
        icon: FileText,
        about: "Policies, contracts and reports that answers can quote, with the page.",
      },
      {
        id: "knowledge",
        label: "Table details",
        icon: Tags,
        about:
          "Describe tables and columns in plain words, link tables, and test how values match.",
      },
    ],
  },
  {
    title: "Teach the AI",
    sections: [
      {
        id: "docs",
        label: "Rules & terms",
        icon: BookOpen,
        about: "Business rules, glossary terms, example questions and shared metrics.",
      },
      {
        id: "benchmarks",
        label: "Accuracy checks",
        icon: Target,
        about: "Questions with known answers, to measure how often the AI gets them right.",
        editorsOnly: true,
      },
      {
        id: "sql",
        label: "SQL editor",
        icon: SquareTerminal,
        about: "Run a query yourself on this space's tables.",
        editorsOnly: true,
      },
    ],
  },
  {
    title: "Manage",
    sections: [
      {
        id: "members",
        label: "People",
        icon: UsersRound,
        about: "Who can use this space, and who can change it.",
      },
      {
        id: "access",
        label: "Data access",
        icon: ShieldCheck,
        about: "Limit which rows and columns each person or group can see.",
        adminsOnly: true,
      },
      {
        id: "settings",
        label: "Settings",
        icon: Settings,
        about: "The space's name, description, tags and starter questions, or delete it.",
        editorsOnly: true,
      },
    ],
  },
];

export function SpacePage() {
  const { spaceId = "" } = useParams();
  const space = useSpace(spaceId);
  const [params, setParams] = useSearchParams();
  const admin = useAuth().hasRole("admin");

  if (space.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-8 w-60" />
        <Skeleton className="mt-8 h-64" />
      </div>
    );
  }
  if (space.isError) {
    const missing = space.error instanceof ApiError && space.error.status === 404;
    return (
      <>
        <BackLink />
        <PageHeader title={missing ? "Space not found" : "Space"} />
        {missing ? (
          <Card>
            <EmptyState icon={SearchX} title="This space doesn't exist, or you're not a member">
              Ask one of its editors to add you.
            </EmptyState>
          </Card>
        ) : (
          <Notice tone="error" title="Could not load the space">
            {space.error.message}
          </Notice>
        )}
      </>
    );
  }

  const editor = space.data.my_role === "editor";
  const groups = GROUPS.map((group) => ({
    ...group,
    sections: group.sections.filter(
      (item) => (editor || !item.editorsOnly) && (admin || !item.adminsOnly),
    ),
  })).filter((group) => group.sections.length > 0);
  const all = groups.flatMap((group) => group.sections);
  const requested = params.get("tab");
  const current = all.find((item) => item.id === requested) ?? all[0];
  const active = current?.id ?? "data";
  const select = (id: TabId) =>
    setParams(id === "data" ? {} : { tab: id }, { replace: true, preventScrollReset: true });

  return (
    <>
      <SpaceHeader space={space.data} editor={editor} />
      <div className="grid gap-6 lg:grid-cols-[13.5rem_minmax(0,1fr)] lg:gap-10">
        <SpaceNav groups={groups} active={active} onSelect={select} />
        <section
          id={`panel-${active}`}
          aria-labelledby={`section-${active}`}
          className="min-w-0 pb-10"
        >
          {current && (
            <div className="mb-6">
              <h2 id={`section-${active}`} className="text-[18px] font-semibold tracking-[-0.01em]">
                {current.label}
              </h2>
              <p className="mt-1 max-w-2xl text-[14px] leading-6 text-muted">{current.about}</p>
            </div>
          )}
          <FadeSwitch id={active}>
            {active === "data" && <DataTab space={space.data} />}
            {active === "knowledge" && <MetadataTab space={space.data} />}
            {active === "docs" && <KnowledgeTab space={space.data} />}
            {active === "library" && <DocumentsTab space={space.data} />}
            {active === "sql" && <SqlTab space={space.data} />}
            {active === "benchmarks" && <BenchmarksTab space={space.data} />}
            {active === "access" && <AccessTab space={space.data} />}
            {active === "members" && <MembersTab space={space.data} />}
            {active === "settings" && <SettingsTab space={space.data} />}
          </FadeSwitch>
        </section>
      </div>
    </>
  );
}

/** The space's mark, name and description, and the one thing most people come here to do. */
function SpaceHeader({ space, editor }: { space: Space; editor: boolean }) {
  useEffect(() => {
    document.title = `${space.name} · Eye of Ender`;
  }, [space.name]);

  return (
    <header className="mb-8 border-b border-border pb-6">
      <Link
        to="/spaces"
        className="mb-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-muted transition-colors hover:text-fg"
      >
        <ArrowLeft aria-hidden className="size-3.5" />
        All spaces
      </Link>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <span
            aria-hidden
            className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent ring-1 ring-border"
          >
            <Boxes className="size-6" />
          </span>
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="truncate text-[24px] leading-tight font-semibold tracking-[-0.015em]">
                {space.name}
              </h1>
              <Badge tone={editor ? "accent" : "neutral"}>{editor ? "Editor" : "Viewer"}</Badge>
            </div>
            {space.description && space.description !== space.name && (
              <p className="max-w-2xl text-[14px] leading-6 text-muted">{space.description}</p>
            )}
            <p className="text-[13px] text-subtle">
              {plural(space.table_count, "table")} · {plural(space.member_count, "person")}
            </p>
          </div>
        </div>
        <Link
          to={`/spaces/${space.id}/chat`}
          className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-accent-fg shadow-card transition-colors hover:bg-accent/90 focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none"
        >
          <MessageSquare aria-hidden className="size-4" />
          Ask questions
        </Link>
      </div>
    </header>
  );
}

/** The sections of a space. A grouped menu down the left on a wide screen; a row you can scroll
 * sideways on a narrow one. */
function SpaceNav({
  groups,
  active,
  onSelect,
}: {
  groups: Array<{ title: string; sections: Section[] }>;
  active: TabId;
  onSelect: (id: TabId) => void;
}) {
  const barId = useId();
  return (
    <nav aria-label="Space sections" className="lg:sticky lg:top-6 lg:self-start">
      <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 lg:hidden">
        {groups
          .flatMap((group) => group.sections)
          .map((item) => (
            <button
              key={item.id}
              type="button"
              aria-current={item.id === active ? "page" : undefined}
              onClick={() => onSelect(item.id)}
              className={cn(
                "flex h-9 shrink-0 items-center gap-2 rounded-full border px-3.5 text-[13px] font-medium transition-colors",
                item.id === active
                  ? "border-accent/40 bg-accent-soft text-fg"
                  : "border-border text-muted hover:bg-surface-2 hover:text-fg",
              )}
            >
              <item.icon aria-hidden className="size-3.5" />
              {item.label}
            </button>
          ))}
      </div>
      <div className="hidden space-y-5 lg:block">
        {groups.map((group) => (
          <div key={group.title}>
            <p className="px-3 pb-1.5 text-[11px] font-semibold tracking-wide text-subtle uppercase">
              {group.title}
            </p>
            <ul className="space-y-0.5">
              {group.sections.map((item) => {
                const selected = item.id === active;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      aria-current={selected ? "page" : undefined}
                      onClick={() => onSelect(item.id)}
                      className={cn(
                        "relative flex h-9 w-full items-center gap-2.5 rounded-lg px-3 text-left text-[13.5px] font-medium transition-colors",
                        "focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none",
                        selected
                          ? "bg-surface-2 text-fg"
                          : "text-muted hover:bg-surface-2/60 hover:text-fg",
                      )}
                    >
                      {selected && (
                        <motion.span
                          layoutId={barId}
                          className="absolute top-2 bottom-2 left-0 w-0.5 rounded-full bg-accent"
                          transition={{ type: "spring", bounce: 0.15, duration: 0.35 }}
                        />
                      )}
                      <item.icon
                        aria-hidden
                        className={cn("size-4 shrink-0", selected && "text-accent")}
                      />
                      {item.label}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}

function BackLink() {
  return (
    <Link
      to="/spaces"
      className="mb-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-muted transition-colors hover:text-fg"
    >
      <ArrowLeft aria-hidden className="size-3.5" />
      All spaces
    </Link>
  );
}

function SettingsTab({ space }: { space: Space }) {
  const update = useUpdateSpace(space.id);
  const remove = useDeleteSpace(space.id);
  const navigate = useNavigate();
  const [name, setName] = useState(space.name);
  const [description, setDescription] = useState(space.description);
  const [tags, setTags] = useState(space.tags.join(", "));
  const [questions, setQuestions] = useState(space.suggested_questions.join("\n"));
  const [saved, setSaved] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const updateError = update.error ? asApiError(update.error) : null;
  const removeError = remove.error ? asApiError(remove.error) : null;
  const tagList = parseSynonyms(tags);
  const questionList = questions
    .split("\n")
    .map((q) => q.trim())
    .filter(Boolean);
  const changed =
    name.trim() !== space.name ||
    description.trim() !== space.description ||
    tagList.join("\u0000") !== space.tags.join("\u0000") ||
    questionList.join("\u0000") !== space.suggested_questions.join("\u0000");

  // Ask again if the confirmation is left open and forgotten.
  useEffect(() => {
    if (!confirming) return;
    const timer = setTimeout(() => setConfirming(false), 8000);
    return () => clearTimeout(timer);
  }, [confirming]);

  function save(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setSaved(false);
    update.mutate(
      {
        name: name.trim(),
        description: description.trim(),
        tags: tagList,
        suggested_questions: questionList,
      },
      { onSuccess: () => setSaved(true) },
    );
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="About"
          description="How this space is described to the people who use it."
        />
        <form onSubmit={save} noValidate className="space-y-4 p-5">
          {updateError && updateError.code !== "validation_error" && (
            <Notice tone="error" title="Not saved">
              {updateError.message}
            </Notice>
          )}
          <TextField
            label="Name"
            maxLength={80}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setSaved(false);
            }}
            error={name.trim() ? updateError?.fieldErrors.name : "Give the space a name."}
          />
          <TextField
            label="Description"
            maxLength={500}
            value={description}
            onChange={(event) => {
              setDescription(event.target.value);
              setSaved(false);
            }}
            error={updateError?.fieldErrors.description}
          />
          <TextField
            label="Tags"
            placeholder="sales, india, quarterly"
            hint="Separated by commas. Up to 10."
            value={tags}
            onChange={(event) => {
              setTags(event.target.value);
              setSaved(false);
            }}
            error={updateError?.fieldErrors.tags}
          />
          <div className="space-y-1.5">
            <label htmlFor="suggested-questions" className="block text-[13px] font-medium">
              Suggested questions
            </label>
            <BareTextArea
              id="suggested-questions"
              rows={3}
              placeholder={"What was revenue last quarter?\nWhich region is growing fastest?"}
              value={questions}
              onChange={(event) => {
                setQuestions(event.target.value);
                setSaved(false);
              }}
            />
            <p className="text-[12.5px] text-subtle">
              One per line, up to 8. They are shown first when someone starts a new chat.
            </p>
            {updateError?.fieldErrors.suggested_questions && (
              <p className="text-[12.5px] text-danger">
                {updateError.fieldErrors.suggested_questions}
              </p>
            )}
          </div>
          <p className="text-[13px] text-muted">Owner: {space.owner_name ?? "unknown"}</p>
          <div className="flex items-center justify-end gap-3">
            {saved && !changed && (
              <p role="status" className="text-[13px] text-muted">
                Saved.
              </p>
            )}
            <Button
              type="submit"
              variant="primary"
              loading={update.isPending}
              disabled={!changed || !name.trim()}
            >
              Save
            </Button>
          </div>
        </form>
      </Card>

      <SearchTester spaceId={space.id} />

      <Card className="border-danger/30">
        <CardHeader
          title="Delete this space"
          description="Removes its tables, uploaded files and members. Delta folders on disk are not touched. This can't be undone."
          aside={
            confirming ? (
              <>
                <Button size="sm" onClick={() => setConfirming(false)}>
                  Keep it
                </Button>
                <Button
                  size="sm"
                  className="border-danger/40 text-danger hover:border-danger hover:bg-danger-soft"
                  loading={remove.isPending}
                  onClick={() =>
                    remove.mutate(undefined, { onSuccess: () => void navigate("/spaces") })
                  }
                >
                  Delete for good
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                className="text-danger hover:bg-danger-soft"
                onClick={() => setConfirming(true)}
              >
                Delete space
              </Button>
            )
          }
          className="border-b-0"
        />
        {removeError && (
          <div className="px-5 pb-5">
            <Notice tone="error" title="Not deleted">
              {removeError.message}
            </Notice>
          </div>
        )}
      </Card>
    </div>
  );
}
