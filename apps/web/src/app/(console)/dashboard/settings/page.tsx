"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { ErrorState } from "@/components/console/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";

interface OrganizationDetail {
  id: string;
  name: string;
  slug: string;
  plan: string;
  region: string;
  billing_email: string | null;
  created_at: string;
}

export default function GeneralSettingsPage() {
  const queryClient = useQueryClient();
  const organizationId = useAuthStore((state) => state.organization?.id ?? "");
  const can = useAuthStore((state) => state.can);
  const editable = can("settings:update");

  const query = useQuery({
    queryKey: queryKeys.organization(organizationId),
    queryFn: () => api.get<OrganizationDetail>("/v1/console/organizations/current"),
    enabled: !!organizationId,
  });

  const [name, setName] = React.useState("");
  const [billingEmail, setBillingEmail] = React.useState("");

  React.useEffect(() => {
    if (query.data) {
      setName(query.data.name);
      setBillingEmail(query.data.billing_email ?? "");
    }
  }, [query.data]);

  const save = useMutation({
    mutationFn: () =>
      api.patch<OrganizationDetail>("/v1/console/organizations/current", {
        name,
        billing_email: billingEmail || null,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.organization(organizationId), updated);
      toast.success("Organization updated.");
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : "Could not save changes."),
  });

  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }

  if (query.isLoading) {
    return (
      <Card className="space-y-4 p-6">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-9 w-full" />
      </Card>
    );
  }

  const dirty = name !== query.data?.name || billingEmail !== (query.data?.billing_email ?? "");

  return (
    <div className="space-y-4">
      <Card className="p-6">
        <h2 className="font-medium">Organization</h2>
        <p className="text-muted-foreground mt-1 text-sm">
          The name your team sees. The slug is immutable — it appears in URLs and support tickets.
        </p>

        <form
          className="mt-6 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="org-name">Name</Label>
            <Input
              id="org-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={!editable || save.isPending}
              maxLength={120}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="billing-email">Billing email</Label>
            <Input
              id="billing-email"
              type="email"
              value={billingEmail}
              onChange={(event) => setBillingEmail(event.target.value)}
              disabled={!editable || save.isPending}
              placeholder="billing@example.com"
            />
            <p className="text-muted-foreground text-xs">
              Invoices and quota warnings go here. Leave blank to use the owner&apos;s address.
            </p>
          </div>

          {editable ? (
            <Button type="submit" disabled={!dirty || save.isPending}>
              {save.isPending ? (
                <>
                  <Loader2 className="animate-spin" /> Saving…
                </>
              ) : (
                "Save changes"
              )}
            </Button>
          ) : (
            // Disabled controls plus an explanation. The server enforces this
            // independently; the UI only avoids offering a guaranteed 403.
            <p className="text-muted-foreground text-sm">
              Your role can view these settings but not change them. Ask an Owner or Admin.
            </p>
          )}
        </form>
      </Card>

      <Card className="p-6">
        <h2 className="font-medium">Details</h2>
        <dl className="mt-4 space-y-3 text-sm">
          <Row
            label="Organization ID"
            value={<code className="font-mono text-xs">{query.data?.id}</code>}
          />
          <Row label="Slug" value={<code className="font-mono text-xs">{query.data?.slug}</code>} />
          <Row label="Plan" value={<Badge variant="secondary">{query.data?.plan}</Badge>} />
          <Row
            label="Data region"
            value={<code className="font-mono text-xs">{query.data?.region}</code>}
          />
        </dl>
        <p className="text-muted-foreground mt-4 text-xs leading-relaxed">
          Data residency is enforced at deploy time and recorded here, so an auditor can see which
          region this tenant was provisioned in.
        </p>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{value}</dd>
    </div>
  );
}
