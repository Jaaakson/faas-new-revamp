"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, MoreHorizontal, UserRoundPlus } from "lucide-react";
import { toast } from "sonner";

import { ErrorState } from "@/components/console/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api } from "@/lib/api-client";
import { absoluteTime, relativeTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

interface Member {
  id: string;
  user_id: string;
  email: string;
  full_name: string | null;
  role: string;
  status: string;
  joined_at: string | null;
}

interface Invitation {
  id: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
  created_at: string;
}

const ROLES = ["owner", "admin", "developer", "viewer"];

export default function MembersPage() {
  const queryClient = useQueryClient();
  const organizationId = useAuthStore((state) => state.organization?.id ?? "");
  const currentUserId = useAuthStore((state) => state.user?.id);
  const can = useAuthStore((state) => state.can);

  const [inviteOpen, setInviteOpen] = React.useState(false);

  const members = useQuery({
    queryKey: queryKeys.members(organizationId),
    queryFn: () => api.get<Member[]>("/v1/console/members"),
    enabled: !!organizationId,
  });

  const invitations = useQuery({
    queryKey: queryKeys.invitations(organizationId),
    queryFn: () => api.get<Invitation[]>("/v1/console/invitations"),
    enabled: !!organizationId && can("member:read"),
  });

  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) =>
      api.patch(`/v1/console/members/${id}`, { role }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.members(organizationId) });
      toast.success("Role updated.");
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Could not change that role."),
  });

  const removeMember = useMutation({
    mutationFn: (id: string) => api.delete(`/v1/console/members/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.members(organizationId) });
      toast.success("Member removed.");
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Could not remove that member."),
  });

  const owners = (members.data ?? []).filter(
    (member) => member.role === "owner" && member.status === "active",
  );

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <h2 className="font-medium">Members</h2>
            <p className="text-muted-foreground mt-0.5 text-sm">
              Everyone with access to this organization.
            </p>
          </div>
          {can("member:invite") ? (
            <Button size="sm" onClick={() => setInviteOpen(true)}>
              <UserRoundPlus /> Invite
            </Button>
          ) : null}
        </div>

        {members.isError ? (
          <div className="p-5">
            <ErrorState error={members.error} onRetry={() => void members.refetch()} />
          </div>
        ) : members.isLoading ? (
          <div className="divide-y">
            {Array.from({ length: 3 }, (_, index) => (
              <div key={index} className="flex items-center gap-4 px-5 py-3">
                <Skeleton className="size-8 rounded-full" />
                <Skeleton className="h-4 w-40" />
                <Skeleton className="ml-auto h-5 w-20 rounded-full" />
              </div>
            ))}
          </div>
        ) : (
          <ul className="divide-y">
            {members.data?.map((member) => {
              // The last active Owner cannot be demoted or removed. Enforced on
              // the server; disabled here so the option is never offered.
              const isLastOwner = member.role === "owner" && owners.length === 1;
              const isSelf = member.user_id === currentUserId;

              return (
                <li key={member.id} className="flex items-center gap-3 px-5 py-3">
                  <span className="bg-muted flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-medium">
                    {(member.full_name ?? member.email).charAt(0).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {member.full_name ?? member.email}
                      {isSelf ? (
                        // The leading space is inside the string, not just a
                        // margin: a screen reader reads adjacent inline
                        // elements with no separator, so a margin alone
                        // announces "Rani Wulandari(you)".
                        <span className="text-muted-foreground ml-1.5 text-xs"> (you)</span>
                      ) : null}
                    </p>
                    <p className="text-muted-foreground truncate text-xs">{member.email}</p>
                  </div>

                  <Badge variant="outline" className="shrink-0 capitalize">
                    {member.role}
                  </Badge>

                  {member.joined_at ? (
                    <span
                      className="text-muted-foreground hidden shrink-0 text-xs sm:inline"
                      title={absoluteTime(member.joined_at)}
                    >
                      joined {relativeTime(member.joined_at)}
                    </span>
                  ) : null}

                  {can("member:update_role") ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="shrink-0"
                          aria-label={`Manage ${member.email}`}
                          disabled={isLastOwner}
                          title={
                            isLastOwner
                              ? "An organization must always have at least one Owner"
                              : undefined
                          }
                        >
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {ROLES.filter((role) => role !== member.role).map((role) => (
                          <DropdownMenuItem
                            key={role}
                            onSelect={() => changeRole.mutate({ id: member.id, role })}
                          >
                            Change to <span className="font-medium capitalize">{role}</span>
                          </DropdownMenuItem>
                        ))}
                        <DropdownMenuItem
                          destructive
                          onSelect={() => removeMember.mutate(member.id)}
                        >
                          Remove from organization
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {can("member:read") && (invitations.data?.length ?? 0) > 0 ? (
        <Card className="overflow-hidden">
          <div className="border-b px-5 py-4">
            <h2 className="font-medium">Pending invitations</h2>
            <p className="text-muted-foreground mt-0.5 text-sm">
              Invitations expire after seven days.
            </p>
          </div>
          <ul className="divide-y">
            {invitations.data?.map((invitation) => (
              <li key={invitation.id} className="flex items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{invitation.email}</p>
                  <p className="text-muted-foreground text-xs">
                    expires {relativeTime(invitation.expires_at)}
                  </p>
                </div>
                <Badge variant="warning" className="capitalize">
                  {invitation.role}
                </Badge>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <InviteDialog
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        organizationId={organizationId}
      />
    </div>
  );
}

function InviteDialog({
  open,
  onOpenChange,
  organizationId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  organizationId: string;
}) {
  const queryClient = useQueryClient();
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState("developer");

  const invite = useMutation({
    mutationFn: () => api.post("/v1/console/invitations", { email, role }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.invitations(organizationId),
      });
      toast.success(`Invitation created for ${email}.`, {
        description:
          "Email delivery is not wired up yet — copy the link from the invitations list.",
      });
      setEmail("");
      onOpenChange(false);
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Could not create that invitation."),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a member</DialogTitle>
          <DialogDescription>
            They will join with the role you choose. The invitation is bound to this address and
            expires in seven days.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            invite.mutate();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="invite-email">Email</Label>
            <Input
              id="invite-email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="colleague@example.com"
            />
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Role</legend>
            <div className="flex flex-wrap gap-2">
              {ROLES.map((option) => (
                <label
                  key={option}
                  className={`focus-within:ring-ring cursor-pointer rounded-md border px-3 py-1.5 text-sm capitalize transition-colors focus-within:ring-2 ${
                    role === option
                      ? "border-primary bg-primary/10 text-primary font-medium"
                      : "text-muted-foreground hover:bg-accent"
                  }`}
                >
                  <input
                    type="radio"
                    name="role"
                    value={option}
                    checked={role === option}
                    onChange={() => setRole(option)}
                    className="sr-only"
                  />
                  {option}
                </label>
              ))}
            </div>
          </fieldset>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={invite.isPending || !email}>
              {invite.isPending ? (
                <>
                  <Loader2 className="animate-spin" /> Creating…
                </>
              ) : (
                "Send invitation"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
