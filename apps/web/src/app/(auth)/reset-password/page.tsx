"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { CircleAlert, CircleCheck, Loader2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Field, PasswordInput } from "@/components/auth/form-field";
import { Button } from "@/components/ui/button";
import { ApiError, apiFetch } from "@/lib/api-client";
import { resetPasswordSchema, type ResetPasswordValues } from "@/lib/auth/schemas";

function ResetPasswordForm() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token");
  const [done, setDone] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { password: "", confirm: "" },
  });

  async function onSubmit(values: ResetPasswordValues) {
    if (!token) return;
    setFormError(null);
    try {
      await apiFetch("/v1/console/auth/reset-password", {
        method: "POST",
        body: { token, password: values.password },
      });
      setDone(true);
      toast.success("Password updated. Sign in with your new password.");
      setTimeout(() => router.replace("/login"), 2500);
    } catch (error) {
      if (error instanceof ApiError) {
        setFormError(error.message);
        return;
      }
      toast.error("Could not reach the service. Check your connection.");
    }
  }

  if (!token) {
    return (
      <div>
        <CircleAlert className="text-destructive size-8" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">Link incomplete</h1>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          This reset link is missing its token. It may have been truncated by your email client —
          try copying the full URL, or request a new link.
        </p>
        <Button className="mt-6 w-full" asChild>
          <Link href="/forgot-password">Request a new link</Link>
        </Button>
      </div>
    );
  }

  if (done) {
    return (
      <div>
        <CircleCheck className="text-success size-8" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">Password updated</h1>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          Every other session has been signed out. Taking you to sign in…
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Choose a new password</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        This will sign out every other session on your account.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-4">
        {formError ? (
          <div
            className="border-destructive/30 bg-destructive/5 text-destructive rounded-lg border p-3 text-sm"
            role="alert"
          >
            {formError}{" "}
            <Link href="/forgot-password" className="underline underline-offset-4">
              Request a new link
            </Link>
          </div>
        ) : null}

        <Field id="password" label="New password" error={errors.password?.message}>
          <PasswordInput
            id="password"
            autoComplete="new-password"
            autoFocus
            showStrength
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? "password-error" : undefined}
            {...register("password")}
            value={watch("password")}
          />
        </Field>

        <Field id="confirm" label="Confirm password" error={errors.confirm?.message}>
          <PasswordInput
            id="confirm"
            autoComplete="new-password"
            aria-invalid={!!errors.confirm}
            aria-describedby={errors.confirm ? "confirm-error" : undefined}
            {...register("confirm")}
            value={watch("confirm")}
          />
        </Field>

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? (
            <>
              <Loader2 className="animate-spin" /> Updating…
            </>
          ) : (
            "Update password"
          )}
        </Button>
      </form>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <React.Suspense fallback={<div className="h-72" aria-hidden />}>
      <ResetPasswordForm />
    </React.Suspense>
  );
}
