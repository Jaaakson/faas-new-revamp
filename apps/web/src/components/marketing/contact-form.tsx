"use client";

import * as React from "react";
import { CircleCheck, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type Topic = "sales" | "support" | "enterprise" | "security" | "other";

const TOPICS: { value: Topic; label: string }[] = [
  { value: "sales", label: "Talk to sales" },
  { value: "enterprise", label: "Enterprise, residency, or on-premise" },
  { value: "support", label: "Technical support" },
  { value: "security", label: "Report a security issue" },
  { value: "other", label: "Something else" },
];

interface Errors {
  name?: string;
  email?: string;
  message?: string;
}

/**
 * Contact form with client-side validation and all four states.
 *
 * Submission is not wired to a backend yet — the transactional email path lands
 * with the rest of the auth flows in Phase 3. Rather than fake a success the
 * user would trust, the success state says plainly that the form is not live
 * and gives the real mailto as the working alternative.
 */
export function ContactForm({ defaultTopic }: { defaultTopic?: string }) {
  const initialTopic = TOPICS.some((t) => t.value === defaultTopic)
    ? (defaultTopic as Topic)
    : "sales";

  const [topic, setTopic] = React.useState<Topic>(initialTopic);
  const [status, setStatus] = React.useState<"idle" | "submitting" | "sent">("idle");
  const [errors, setErrors] = React.useState<Errors>({});

  function validate(form: FormData): Errors {
    const next: Errors = {};
    const name = String(form.get("name") ?? "").trim();
    const email = String(form.get("email") ?? "").trim();
    const message = String(form.get("message") ?? "").trim();

    if (name.length < 2) next.name = "Please enter your name.";
    // Deliberately permissive: strict email regexes reject valid addresses, and
    // the real check is whether the message arrives.
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      next.email = "Please enter a valid email address.";
    }
    if (message.length < 20) {
      next.message = "A little more detail helps us route this to the right person.";
    }
    return next;
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const found = validate(form);
    setErrors(found);
    if (Object.keys(found).length > 0) {
      // Move focus to the first invalid field so a keyboard user is not left
      // guessing what failed.
      const firstKey = Object.keys(found)[0]!;
      document.getElementById(firstKey)?.focus();
      return;
    }

    setStatus("submitting");
    await new Promise((resolve) => setTimeout(resolve, 600));
    setStatus("sent");
  }

  if (status === "sent") {
    return (
      <div
        className="border-success/30 bg-success/5 rounded-lg border p-6"
        role="status"
        aria-live="polite"
      >
        <CircleCheck className="text-success size-6" aria-hidden />
        <h2 className="mt-3 font-medium">Thanks — but read this first</h2>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          This form is not connected to a mailbox yet. Transactional email lands with the
          authentication work in the next release, and we would rather tell you that than let a real
          message disappear.
        </p>
        <p className="text-muted-foreground mt-3 text-sm leading-relaxed">
          In the meantime, email{" "}
          <a className="text-primary underline underline-offset-4" href="mailto:hello@fvas.io">
            hello@fvas.io
          </a>
          . For anything security-related, use{" "}
          <a className="text-primary underline underline-offset-4" href="mailto:security@fvas.io">
            security@fvas.io
          </a>{" "}
          — never a public channel.
        </p>
        <Button variant="outline" className="mt-5" onClick={() => setStatus("idle")}>
          Back to the form
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      <fieldset>
        <legend className="text-sm font-medium">What is this about?</legend>
        <div className="mt-3 flex flex-wrap gap-2">
          {TOPICS.map((option) => (
            <label
              key={option.value}
              className={`focus-within:ring-ring cursor-pointer rounded-md border px-3 py-1.5 text-sm transition-colors focus-within:ring-2 focus-within:ring-offset-2 ${
                topic === option.value
                  ? "border-primary bg-primary/10 text-primary font-medium"
                  : "text-muted-foreground hover:bg-accent"
              }`}
            >
              <input
                type="radio"
                name="topic"
                value={option.value}
                checked={topic === option.value}
                onChange={() => setTopic(option.value)}
                className="sr-only"
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>

      {topic === "security" ? (
        <div className="border-warning/30 bg-warning/5 rounded-lg border p-4 text-sm">
          <p className="font-medium">Please email us instead</p>
          <p className="text-muted-foreground mt-1 leading-relaxed">
            Security reports go to{" "}
            <a className="text-primary underline underline-offset-4" href="mailto:security@fvas.io">
              security@fvas.io
            </a>{" "}
            so they stay private. Never file a vulnerability in a public channel.
          </p>
        </div>
      ) : null}

      <Field id="name" label="Name" error={errors.name}>
        <Input
          id="name"
          name="name"
          autoComplete="name"
          aria-invalid={!!errors.name}
          aria-describedby={errors.name ? "name-error" : undefined}
        />
      </Field>

      <Field id="email" label="Work email" error={errors.email}>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? "email-error" : undefined}
        />
      </Field>

      <Field id="company" label="Company" hint="Optional">
        <Input id="company" name="company" autoComplete="organization" />
      </Field>

      <Field
        id="message"
        label="Message"
        error={errors.message}
        hint="What are you building, and where would verification fit?"
      >
        <Textarea
          id="message"
          name="message"
          rows={5}
          aria-invalid={!!errors.message}
          aria-describedby={errors.message ? "message-error" : undefined}
        />
      </Field>

      <Button type="submit" disabled={status === "submitting"}>
        {status === "submitting" ? (
          <>
            <Loader2 className="animate-spin" /> Sending…
          </>
        ) : (
          "Send message"
        )}
      </Button>
    </form>
  );
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Label htmlFor={id}>{label}</Label>
        {hint && !error ? <span className="text-muted-foreground text-xs">{hint}</span> : null}
      </div>
      {children}
      {error ? (
        // Linked by id so the error is announced with the field, not stranded.
        <p id={`${id}-error`} className="text-destructive text-xs" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
