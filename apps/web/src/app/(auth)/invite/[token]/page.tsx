"use client";

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Building2, CircleAlert, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { RegisterForm } from "@/components/auth/register-form";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

interface InvitationPreview {
  organization_name: string;
  email: string;
  role: string;
  expires_at: string;
}

type State =
  | { kind: "loading" }
  | { kind: "ready"; preview: InvitationPreview }
  | { kind: "invalid"; message: string };

export default function InvitePage() {
  const params = useParams<{ token: string }>();
  const router = useRouter();
  const token = params.token;

  const status = useAuthStore((state) => state.status);
  const user = useAuthStore((state) => state.user);
  const [state, setState] = React.useState<State>({ kind: "loading" });
  const [accepting, setAccepting] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;

    // Unauthenticated on purpose: the recipient may not have an account yet.
    apiFetch<InvitationPreview>(`/v1/console/invitations/preview/${token}`)
      .then((preview) => !cancelled && setState({ kind: "ready", preview }))
      .catch(
        (error: unknown) =>
          !cancelled &&
          setState({
            kind: "invalid",
            message:
              error instanceof ApiError
                ? error.message
                : "Could not reach the service. Check your connection.",
          }),
      );

    return () => {
      cancelled = true;
    };
  }, [token]);

  async function accept() {
    setAccepting(true);
    try {
      await apiFetch("/v1/console/invitations/accept", {
        method: "POST",
        body: { token },
      });
      toast.success("You've joined the organization.");
      router.replace("/dashboard");
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not accept the invitation.");
      setAccepting(false);
    }
  }

  if (state.kind === "loading") {
    return (
      <div className="flex flex-col items-center py-12" aria-live="polite">
        <Loader2 className="text-muted-foreground size-8 animate-spin" aria-hidden />
        <p className="text-muted-foreground mt-4 text-sm">Checking your invitation…</p>
      </div>
    );
  }

  if (state.kind === "invalid") {
    return (
      <div>
        <CircleAlert className="text-destructive size-8" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">
          This invitation isn&apos;t valid
        </h1>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          {state.message} Invitations expire after 7 days and can be revoked by the organization.
          Ask whoever invited you to send a new one.
        </p>
        <Button variant="outline" className="mt-6 w-full" asChild>
          <Link href="/">Back to homepage</Link>
        </Button>
      </div>
    );
  }

  const { preview } = state;

  // Already signed in: accept directly rather than forcing a second account.
  if (status === "authenticated" && user) {
    const mismatch = user.email !== preview.email;

    return (
      <div>
        <Building2 className="text-primary size-8" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">
          Join {preview.organization_name}
        </h1>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          You&apos;ve been invited as a{" "}
          <span className="text-foreground font-medium">{preview.role}</span>.
        </p>

        {mismatch ? (
          <div
            className="border-warning/30 bg-warning/5 mt-6 rounded-lg border p-3 text-sm"
            role="alert"
          >
            This invitation was issued to <span className="font-medium">{preview.email}</span>, but
            you are signed in as <span className="font-medium">{user.email}</span>. Sign in with the
            invited address to accept it.
          </div>
        ) : null}

        <Button className="mt-6 w-full" onClick={accept} disabled={accepting || mismatch}>
          {accepting ? (
            <>
              <Loader2 className="animate-spin" /> Joining…
            </>
          ) : (
            `Join ${preview.organization_name}`
          )}
        </Button>
      </div>
    );
  }

  return (
    <React.Suspense fallback={<div className="h-96" aria-hidden />}>
      <RegisterForm
        invitation={{
          token,
          email: preview.email,
          organization_name: preview.organization_name,
          role: preview.role,
        }}
      />
    </React.Suspense>
  );
}
