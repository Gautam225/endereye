import { UserPlus, UserRoundMinus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { SelectField } from "../../components/ui/Field";
import { Notice } from "../../components/ui/Notice";
import { Skeleton } from "../../components/ui/Skeleton";
import { Badge } from "../../components/ui/Status";
import { asApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { cn } from "../../lib/cn";
import { initials } from "../../lib/format";
import { useDirectory, useMembers, useRemoveMember, useSetMember } from "./queries";
import type { Member, Space, SpaceRole } from "./types";

const ROLE_OPTIONS: Array<{ value: SpaceRole; label: string }> = [
  { value: "viewer", label: "Viewer" },
  { value: "editor", label: "Editor" },
];

const ROLE_HELP: Record<SpaceRole, string> = {
  viewer: "Asks questions and sees the data.",
  editor: "Also adds data and runs SQL.",
};

export function MembersTab({ space }: { space: Space }) {
  // Only an administrator changes who is in a space and their role: a role decides what a person
  // may read and change, so an editor can not hand it out (the server refuses it too).
  const editor = useAuth().hasRole("admin");
  const members = useMembers(space.id);

  return (
    <div className="space-y-5">
      {editor && members.data && <AddMember spaceId={space.id} members={members.data} />}
      <Card>
        <CardHeader
          title="Members"
          description={
            editor
              ? "Admins can open every space and count as editors, even when not listed."
              : "Only an administrator can add people or change their role."
          }
        />
        {members.isPending ? (
          <div className="space-y-3 p-5">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-11" />
            ))}
          </div>
        ) : members.isError ? (
          <div className="p-5">
            <Notice tone="error" title="Could not load members">
              {members.error.message}
            </Notice>
          </div>
        ) : members.data.length === 0 ? (
          <p className="px-5 py-6 text-center text-[13px] text-muted">No members yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {members.data.map((member) => (
              <MemberRow key={member.user_id} spaceId={space.id} member={member} editor={editor} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function AddMember({ spaceId, members }: { spaceId: string; members: Member[] }) {
  const directory = useDirectory(true);
  const add = useSetMember(spaceId);
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<SpaceRole>("viewer");
  const error = add.error ? asApiError(add.error) : null;
  const inSpace = new Set(members.map((member) => member.user_id));
  const candidates = (directory.data ?? []).filter((person) => !inSpace.has(person.id));
  const chosen = candidates.some((person) => person.id === userId) ? userId : "";

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!chosen) return;
    add.mutate({ userId: chosen, role }, { onSuccess: () => setUserId("") });
  }

  return (
    <Card>
      <CardHeader title="Add someone" />
      <form onSubmit={submit} className="space-y-4 p-5">
        {(error || directory.isError) && (
          <Notice tone="error" title={error ? "Not added" : "Could not load people"}>
            {error?.message ?? directory.error?.message}
          </Notice>
        )}
        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-start">
          <SelectField
            label="Person"
            value={chosen}
            onChange={(event) => setUserId(event.target.value)}
            disabled={directory.isPending || candidates.length === 0}
            options={[
              {
                value: "",
                label: directory.isPending
                  ? "Loading…"
                  : candidates.length
                    ? "Choose a person"
                    : "Everyone is already a member",
              },
              ...candidates.map((person) => ({
                value: person.id,
                label: `${person.full_name} (${person.email})`,
              })),
            ]}
          />
          <div className="space-y-1.5">
            <SelectField
              label="Role"
              value={role}
              onChange={(event) => setRole(event.target.value as SpaceRole)}
              options={ROLE_OPTIONS}
            />
            <p className="text-[12.5px] text-subtle">{ROLE_HELP[role]}</p>
          </div>
          <Button
            type="submit"
            variant="primary"
            className="sm:mt-[1.6rem]"
            loading={add.isPending}
            disabled={!chosen}
          >
            <UserPlus aria-hidden />
            Add
          </Button>
        </div>
      </form>
    </Card>
  );
}

function MemberRow({
  spaceId,
  member,
  editor,
}: {
  spaceId: string;
  member: Member;
  editor: boolean;
}) {
  const { user: me } = useAuth();
  const setRole = useSetMember(spaceId);
  const remove = useRemoveMember(spaceId);
  const failed = setRole.error ?? remove.error;
  const error = failed ? asApiError(failed) : null;
  const isMe = me?.id === member.user_id;
  const busy = setRole.isPending || remove.isPending;

  return (
    <li className="px-5 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <span
          aria-hidden
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold",
            member.is_active ? "bg-accent-soft text-accent" : "bg-surface-2 text-subtle",
          )}
        >
          {initials(member.full_name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">
            {member.full_name}
            {isMe && <span className="ml-1.5 font-normal text-subtle">(you)</span>}
            {!member.is_active && (
              <span className="ml-1.5 font-normal text-subtle">· account turned off</span>
            )}
          </p>
          <p className="truncate text-[13px] text-muted">{member.email}</p>
        </div>
        {editor ? (
          <div className="flex items-center gap-1">
            <div className="w-28">
              <SelectField
                label={`Role for ${member.full_name}`}
                hideLabel
                value={member.role}
                disabled={busy}
                options={ROLE_OPTIONS}
                onChange={(event) =>
                  setRole.mutate({ userId: member.user_id, role: event.target.value as SpaceRole })
                }
                className="h-8 text-[13px]"
              />
            </div>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Remove ${member.full_name} from this space`}
              title="Remove from this space"
              disabled={busy}
              onClick={() => remove.mutate(member.user_id)}
            >
              <UserRoundMinus aria-hidden />
            </Button>
          </div>
        ) : (
          <Badge tone={member.role === "editor" ? "accent" : "neutral"}>
            {member.role === "editor" ? "Editor" : "Viewer"}
          </Badge>
        )}
      </div>
      {error && (
        <Notice tone="error" title="Change not saved" className="mt-3 sm:ml-12">
          {error.message}
        </Notice>
      )}
    </li>
  );
}
