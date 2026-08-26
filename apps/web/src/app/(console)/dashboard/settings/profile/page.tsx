"use client";

import { CircleCheck, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useAuthStore } from "@/stores/auth-store";

export default function ProfileSettingsPage() {
  const user = useAuthStore((state) => state.user);
  const organizations = useAuthStore((state) => state.organizations);
  const permissions = useAuthStore((state) => state.permissions);

  return (
    <div className="space-y-4">
      <Card className="p-6">
        <h2 className="font-medium">Your account</h2>
        <dl className="mt-4 space-y-3 text-sm">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Name</dt>
            <dd>{user?.full_name ?? "—"}</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Email</dt>
            <dd className="flex items-center gap-2">
              {user?.email}
              {user?.email_verified ? (
                <Badge variant="success">
                  <CircleCheck aria-hidden /> verified
                </Badge>
              ) : (
                <Badge variant="warning">
                  <TriangleAlert aria-hidden /> unverified
                </Badge>
              )}
            </dd>
          </div>
        </dl>
      </Card>

      <Card className="p-6">
        <h2 className="font-medium">Organizations</h2>
        <p className="text-muted-foreground mt-1 text-sm">
          One account can belong to several organizations, each with its own role.
        </p>
        <ul className="mt-4 space-y-2">
          {organizations.map((org) => (
            <li key={org.id} className="flex items-center justify-between gap-4 text-sm">
              <span>{org.name}</span>
              <Badge variant="outline" className="capitalize">
                {org.role}
              </Badge>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="p-6">
        <h2 className="font-medium">Your permissions here</h2>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
          Resolved from your role in the active organization. The server enforces these
          independently — the console only uses them to decide what to show.
        </p>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {permissions.map((permission) => (
            <code key={permission} className="bg-muted rounded px-2 py-1 font-mono text-xs">
              {permission}
            </code>
          ))}
        </div>
      </Card>

      <Card className="p-6">
        <h2 className="font-medium">Password and sessions</h2>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
          Changing your password and revoking individual sessions land alongside two-factor
          authentication. Until then, use the forgot-password flow from the sign-in page — it
          invalidates every active session as a side effect.
        </p>
      </Card>
    </div>
  );
}
