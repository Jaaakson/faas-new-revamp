"use client";

import * as React from "react";
import { Eye, EyeOff } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { passwordStrength } from "@/lib/auth/schemas";
import { cn } from "@/lib/utils";

/**
 * A labelled field with its error linked by `aria-describedby`.
 *
 * An error rendered next to an input but not associated with it is invisible to
 * a screen reader — the user hears "edit text, blank" and no reason why their
 * submission failed.
 */
export function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <Label htmlFor={id}>{label}</Label>
        {hint && !error ? hint : null}
      </div>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-destructive text-xs" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export const PasswordInput = React.forwardRef<
  HTMLInputElement,
  React.ComponentProps<"input"> & { showStrength?: boolean; value?: string }
>(({ showStrength = false, className, value, ...props }, ref) => {
  const [visible, setVisible] = React.useState(false);
  const strength = showStrength ? passwordStrength(String(value ?? "")) : null;

  return (
    <div className="space-y-2">
      <div className="relative">
        <Input
          ref={ref}
          type={visible ? "text" : "password"}
          className={cn("pr-10", className)}
          value={value}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((current) => !current)}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring absolute top-1/2 right-1 -translate-y-1/2 rounded p-1.5 focus-visible:ring-2 focus-visible:outline-none"
          // Toggling visibility is a legitimate usability aid; forcing blind
          // typing causes more failed logins than it prevents shoulder-surfing.
          aria-label={visible ? "Hide password" : "Show password"}
        >
          {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>

      {strength && String(value ?? "").length > 0 ? (
        <div>
          <div className="flex gap-1" aria-hidden>
            {[1, 2, 3, 4].map((level) => (
              <div
                key={level}
                className={cn(
                  "h-1 flex-1 rounded-full transition-colors",
                  strength.score >= level
                    ? strength.score <= 1
                      ? "bg-destructive"
                      : strength.score === 2
                        ? "bg-warning"
                        : "bg-success"
                    : "bg-muted",
                )}
              />
            ))}
          </div>
          <p className="text-muted-foreground mt-1 text-xs" role="status">
            {strength.label}
          </p>
        </div>
      ) : null}
    </div>
  );
});
PasswordInput.displayName = "PasswordInput";
