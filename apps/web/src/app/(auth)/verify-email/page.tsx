"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CircleAlert, CircleCheck, Loader2, MailCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api-client";

type State =
  | { kind: "idle" }
  | { kind: "verifying" }
  | { kind: "verified" }
  | { kind: "failed"; message: string };

function VerifyEmail() {
  const params = useSearchParams();
  const token = params.get("token");
  const [state, setState] = React.useState<State>({ kind: token ? "verifying" : "idle" });

  React.useEffect(() => {
    if (!token) return;
    let cancelled = false;

    apiFetch("/v1/console/auth/verify-email", { method: "POST", body: { token } })
      .then(() => !cancelled && setState({ kind: "verified" }))
      .catch((error: unknown) => {
        if (cancelled) return;
        setState({
          kind: "failed",
          message:
            error instanceof ApiError
              ? error.message
              : "Could not reach the service. Check your connection.",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  // Arrived without a token — the user clicked "verify" from the console rather
  // than from an email link.
  if (state.kind === "idle") {
    return (
      <div>
        <MailCheck className="text-primary size-8" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">Verify your email</h1>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          We sent a verification link when you signed up. Click it to confirm your address — it is
          required before you can create live API keys.
        </p>
        <Button className="mt-6 w-full" asChild>
          <Link href="/dashboard">Continue to the console</Link>
        </Button>
      </div>
    );
  }

  if (state.kind === "verifying") {
    return (
      <div className="flex flex-col items-center py-12 text-center" aria-live="polite">
        <Loader2 className="text-muted-foreground size-8 animate-spin" aria-hidden />
        <p className="text-muted-foreground mt-4 text-sm">Verifying your email…</p>
      </div>
    );
  }

  if (state.kind === "verified") {
    return (
      <div aria-live="polite">
        <CircleCheck className="text-success size-8" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">Email verified</h1>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          You can now create live API keys and invite your team.
        </p>
        <Button className="mt-6 w-full" asChild>
          <Link href="/dashboard">Go to the console</Link>
        </Button>
      </div>
    );
  }

  return (
    <div aria-live="polite">
      <CircleAlert className="text-destructive size-8" aria-hidden />
      <h1 className="mt-4 text-2xl font-semibold tracking-tight">
        We couldn&apos;t verify that link
      </h1>
      <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{state.message}</p>
      <p className="text-muted-foreground mt-3 text-sm leading-relaxed">
        Verification links expire after 24 hours and can only be used once. Request a fresh one from
        the console.
      </p>
      <Button className="mt-6 w-full" asChild>
        <Link href="/dashboard">Go to the console</Link>
      </Button>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <React.Suspense fallback={<div className="h-64" aria-hidden />}>
      <VerifyEmail />
    </React.Suspense>
  );
}
