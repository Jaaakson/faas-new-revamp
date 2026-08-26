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
import { registerSchema, type RegisterValues } from "@/lib/auth/schemas";
import { useAuthStore } from "@/stores/auth-store";

export function RegisterForm({
  invitation,
}: {
  invitation?: { token: string; email: string; organization_name: string; role: string };
}) {
  const router = useRouter();
  const params = useSearchParams();
  const setSession = useAuthStore((state) => state.setSession);
  const [formError, setFormError] = React.useState<string | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      full_name: "",
      email: invitation?.email ?? "",
      password: "",
      organization_name: "",
    },
  });

  async function onSubmit(values: RegisterValues) {
    setFormError(null);
    try {
      const session = await bffFetch<{
        access_token: string;
        user: Parameters<typeof setSession>[0]["user"];
        organization: Parameters<typeof setSession>[0]["organization"];
      }>("/api/auth/register", {
        ...values,
        // The email is locked to the invitation, so a leaked link cannot be
        // redirected to another address. The server enforces this too.
        email: invitation?.email ?? values.email,
        invitation_token: invitation?.token,
      });

      setSession(session);
      // An invited user joins an existing organization, so onboarding — which
      // exists to create one — would be a pointless detour.
      router.replace(invitation ? "/dashboard" : "/onboarding");
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === "email_taken") {
          setFormError("An account with this email already exists. Try signing in.");
        } else if (error.code === "weak_password") {
          setFormError(error.message);
        } else if (error.status >= 500) {
          toast.error("The service is unavailable. Please try again shortly.");
        } else {
          setFormError(error.message);
        }
        return;
      }
      toast.error("Could not reach the service. Check your connection.");
    }
  }

  const planParam = params.get("plan");

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">
        {invitation ? `Join ${invitation.organization_name}` : "Create your account"}
      </h1>
      <p className="text-muted-foreground mt-2 text-sm">
        {invitation ? (
          <>
            You&apos;ve been invited as a{" "}
            <span className="text-foreground font-medium">{invitation.role}</span>.
          </>
        ) : (
          <>
            Already have an account?{" "}
            <Link href="/login" className="text-primary underline underline-offset-4">
              Sign in
            </Link>
          </>
        )}
      </p>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-4">
        {formError ? (
          <div
            className="border-destructive/30 bg-destructive/5 text-destructive rounded-lg border p-3 text-sm"
            role="alert"
          >
            {formError}
          </div>
        ) : null}

        <Field id="full_name" label="Full name" error={errors.full_name?.message}>
          <Input
            id="full_name"
            autoComplete="name"
            autoFocus
            aria-invalid={!!errors.full_name}
            aria-describedby={errors.full_name ? "full_name-error" : undefined}
            {...register("full_name")}
          />
        </Field>

        <Field id="email" label="Work email" error={errors.email?.message}>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            readOnly={!!invitation}
            className={invitation ? "bg-muted cursor-not-allowed" : undefined}
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? "email-error" : undefined}
            {...register("email")}
          />
        </Field>

        {!invitation ? (
          <Field
            id="organization_name"
            label="Organization"
            error={errors.organization_name?.message}
            hint={<span className="text-muted-foreground text-xs">Optional</span>}
          >
            <Input
              id="organization_name"
              autoComplete="organization"
              placeholder="Acme Corp"
              {...register("organization_name")}
            />
          </Field>
        ) : null}

        <Field id="password" label="Password" error={errors.password?.message}>
          <PasswordInput
            id="password"
            autoComplete="new-password"
            showStrength
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? "password-error" : undefined}
            {...register("password")}
            value={watch("password")}
          />
        </Field>

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? (
            <>
              <Loader2 className="animate-spin" /> Creating account…
            </>
          ) : (
            "Create account"
          )}
        </Button>

        {planParam ? (
          <p className="text-muted-foreground text-center text-xs">
            You selected the {planParam} plan. Billing is not enabled yet — you start on Free.
          </p>
        ) : null}
      </form>
    </div>
  );
}
