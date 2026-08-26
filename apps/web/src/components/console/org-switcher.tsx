"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Building2, Check, ChevronsUpDown, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { ApiError, apiFetch, bffFetch, setAccessToken } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import { cn } from "@/lib/utils";

/**
 * Organization switcher.
 *
 * Switching re-issues the session against the new organization, because the
 * active tenant lives in the access token rather than in a request parameter —
 * a caller cannot address another tenant even by guessing an ID.
 *
 * The cache is cleared *before* navigating. Every console query key begins with
 * the organization id, so stale entries could not be served to the wrong
 * tenant — but leaving them would still render the previous org's numbers for a
 * frame, which in a multi-tenant product looks exactly like a leak.
 */
export function OrgSwitcher({ collapsed = false }: { collapsed?: boolean }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { organization, organizations, setSession, setProfile } = useAuthStore();
  const [switching, setSwitching] = React.useState<string | null>(null);

  async function switchTo(organizationId: string) {
    if (organizationId === organization?.id) return;
    setSwitching(organizationId);

    try {
      const session = await bffFetch<{
        access_token: string;
        user: Parameters<typeof setSession>[0]["user"];
        organization: Parameters<typeof setSession>[0]["organization"];
      }>("/api/auth/switch-organization", { organization_id: organizationId });

      queryClient.clear();
      setAccessToken(session.access_token);
      setSession(session);

      // Permissions come from the role in the *target* organization, and the
      // session payload does not carry them. Without this reload, switching
      // from Owner in one org to Viewer in another would leave the elevated
      // navigation and command-palette actions on screen until a full reload.
      const profile = await apiFetch<{
        user: Parameters<typeof setProfile>[0]["user"];
        organizations: Parameters<typeof setProfile>[0]["organizations"];
        active_organization_id: string | null;
        permissions: string[];
      }>("/v1/console/auth/me");
      setProfile(profile);

      router.replace("/dashboard");
      toast.success(`Switched to ${session.organization?.name}`);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not switch organization.");
    } finally {
      setSwitching(null);
    }
  }

  if (!organization) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "hover:bg-accent focus-visible:ring-ring flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none",
          collapsed && "justify-center px-0",
        )}
        aria-label={`Current organization: ${organization.name}. Switch organization.`}
      >
        <span className="bg-primary/10 text-primary flex size-6 shrink-0 items-center justify-center rounded font-medium">
          {organization.name.charAt(0).toUpperCase()}
        </span>
        {!collapsed ? (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{organization.name}</span>
              <span className="text-muted-foreground block text-xs capitalize">
                {organization.plan}
              </span>
            </span>
            <ChevronsUpDown className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
          </>
        ) : null}
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel className="text-muted-foreground">Organizations</DropdownMenuLabel>
        {organizations.map((org) => (
          <DropdownMenuItem
            key={org.id}
            onSelect={() => void switchTo(org.id)}
            disabled={switching !== null}
          >
            <span className="bg-muted flex size-5 shrink-0 items-center justify-center rounded text-[10px] font-medium">
              {org.name.charAt(0).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1 truncate">{org.name}</span>
            <Badge variant="outline" className="shrink-0 text-[10px]">
              {org.role}
            </Badge>
            {switching === org.id ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : org.id === organization.id ? (
              <Check className="text-primary size-3.5" />
            ) : null}
          </DropdownMenuItem>
        ))}

        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/dashboard/settings")}>
          <Building2 />
          Organization settings
        </DropdownMenuItem>
        <DropdownMenuItem disabled>
          <Plus />
          Create organization
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
