"use client";

import * as React from "react";
import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Loader2, MailCheck } from "lucide-react";
import { useForm } from "react-hook-form";

import { Field } from "@/components/auth/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api-client";
import { forgotPasswordSchema, type ForgotPasswordValues } from "@/lib/auth/schemas";

export default function ForgotPasswordPage() {
  const [sent, setSent] = React.useState(false);

  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<ForgotPasswordValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: "" },
  });

  async function onSubmit(values: ForgotPasswordValues) {
    try {
      await apiFetch("/v1/console/auth/forgot-password", {
        method: "POST",
        body: values,
      });
    } catch {
      // Deliberately swallowed. The server returns the same response whether or
      // not the account exists; showing a different outcome on the client would
      // reintroduce the account-enumeration oracle the API avoids.
    }
    setSent(true);
  }

  if (sent) {
    return (
      <div>
        <MailCheck className="text-success size-8" aria-hidden />
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">Check your inbox</h1>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          If an account exists for{" "}
          <span className="text-foreground font-medium">{getValues("email")}</span>, we have sent a
          reset link. It expires in 30 minutes.
        </p>
        <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
          Nothing arrived? Check spam, or{" "}
          <button
            type="button"
            onClick={() => setSent(false)}
            className="text-primary underline underline-offset-4"
          >
            try a different address
          </button>
          .
        </p>
        <Button variant="outline" className="mt-6 w-full" asChild>
          <Link href="/login">
            <ArrowLeft /> Back to sign in
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Reset your password</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Enter your email and we&apos;ll send you a link.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-4">
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

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? (
            <>
              <Loader2 className="animate-spin" /> Sending…
            </>
          ) : (
            "Send reset link"
          )}
        </Button>

        <Button variant="ghost" className="w-full" asChild>
          <Link href="/login">
            <ArrowLeft /> Back to sign in
          </Link>
        </Button>
      </form>
    </div>
  );
}
