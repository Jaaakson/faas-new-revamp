"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Field, PasswordInput } from "@/components/auth/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, bffFetch } from "@/lib/api-client";
import { loginSchema, type LoginValues } from "@/lib/auth/schemas";
import { useAuthStore } from "@/stores/auth-store";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const setSession = useAuthStore((state) => state.setSession);
  const [formError, setFormError] = React.useState<string | null>(null);

  const next = params.get("next") ?? "/dashboard";
  const expired = params.get("reason") === "expired";

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  async function onSubmit(values: LoginValues) {
    setFormError(null);
    try {
      const session = await bffFetch<{
        access_token: string;
        user: Parameters<typeof setSession>[0]["user"];
        organization: Parameters<typeof setSession>[0]["organization"];
      }>("/api/auth/login", values);

      setSession(session);
      // `next` comes from the URL, so it is attacker-controllable. Only allow a
      // same-origin relative path — otherwise this is an open redirect that
      // sends a freshly authenticated user to a phishing page.
      const target = next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
      router.replace(target);
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "account_locked") {
          setFormError(error.message);
        } else if (error.status >= 500) {
          toast.error("The service is unavailable. Please try again shortly.");
        } else {
          setFormError("Incorrect email or password.");
        }
        return;
      }
      toast.error("Could not reach the service. Check your connection.");
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Sign in to Fvas</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Don&apos;t have an account?{" "}
        <Link href="/register" className="text-primary underline underline-offset-4">
          Start free
        </Link>
      </p>

      {expired ? (
        <div
          className="border-warning/30 bg-warning/5 mt-6 rounded-lg border p-3 text-sm"
          role="status"
        >
          Your session expired. Sign in to pick up where you left off.
        </div>
      ) : null}

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-4">
        {formError ? (
          <div
            className="border-destructive/30 bg-destructive/5 text-destructive rounded-lg border p-3 text-sm"
            role="alert"
          >
            {formError}
          </div>
        ) : null}

        <Field id="email" label="Email" error={errors.email?.message}>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            autoFocus
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? "email-error" : undefined}
            {...register("email")}
          />
        </Field>

        <Field
          id="password"
          label="Password"
          error={errors.password?.message}
          hint={
            <Link
              href="/forgot-password"
              className="text-muted-foreground hover:text-foreground text-xs underline underline-offset-4"
            >
              Forgot password?
            </Link>
          }
        >
          <PasswordInput
            id="password"
            autoComplete="current-password"
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? "password-error" : undefined}
            {...register("password")}
            value={watch("password")}
          />
        </Field>

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? (
            <>
              <Loader2 className="animate-spin" /> Signing in…
            </>
          ) : (
            "Sign in"
          )}
        </Button>
      </form>
    </div>
  );
}
