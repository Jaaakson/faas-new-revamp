"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, Check, Loader2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Field } from "@/components/auth/form-field";
import { CopyButton } from "@/components/copy-button";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch } from "@/lib/api-client";
import { organizationSchema, type OrganizationValues } from "@/lib/auth/schemas";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";

const USE_CASES = [
  { value: "lending", label: "Digital lending or fintech" },
  { value: "healthcare", label: "Healthcare" },
  { value: "logistics", label: "Logistics or field operations" },
  { value: "hr", label: "HR-tech or workforce" },
  { value: "other", label: "Something else" },
];

/**
 * Three-step onboarding.
 *
 * The last step matters most: it ends with a working `curl` the user can copy.
 * They leave onboarding holding something that runs, which is what makes
 * "under ten minutes to first verification" achievable (docs/03 §A1).
 */
export default function OnboardingPage() {
  const router = useRouter();
  const organization = useAuthStore((state) => state.organization);
  const user = useAuthStore((state) => state.user);

  const [step, setStep] = React.useState(1);
  const [useCase, setUseCase] = React.useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<OrganizationValues>({
    resolver: zodResolver(organizationSchema),
    defaultValues: { name: organization?.name ?? "" },
  });

  // Arriving here without a session means the register redirect fired before
  // state settled, or the tab was reopened. Send them to sign in.
  React.useEffect(() => {
    if (useAuthStore.getState().status === "anonymous") router.replace("/login");
  }, [router]);

  async function saveOrganization(values: OrganizationValues) {
    try {
      if (organization && values.name !== organization.name) {
        await apiFetch("/v1/console/organizations/current", {
          method: "PATCH",
          body: { name: values.name },
        });
      }
      setStep(2);
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "Could not save your organization.");
    }
  }

  const curlSample = `curl https://api.fvas.io/v1/subjects \\
  -H "Authorization: Bearer $FVAS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"external_id": "user_84213"}'`;

  return (
    <div>
      <ol className="flex items-center gap-2" aria-label="Onboarding progress">
        {[1, 2, 3].map((index) => (
          <li key={index} className="flex flex-1 items-center gap-2">
            <span
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-medium",
                step > index
                  ? "bg-success text-success-foreground"
                  : step === index
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground",
              )}
              aria-current={step === index ? "step" : undefined}
            >
              {step > index ? <Check className="size-3.5" /> : index}
            </span>
            {index < 3 ? (
              <span
                className={cn("h-px flex-1", step > index ? "bg-success" : "bg-border")}
                aria-hidden
              />
            ) : null}
          </li>
        ))}
      </ol>

      {step === 1 ? (
        <div className="mt-8">
          <h1 className="text-2xl font-semibold tracking-tight">
            Welcome{user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}
          </h1>
          <p className="text-muted-foreground mt-2 text-sm">
            What should we call your organization? You can change this later.
          </p>

          <form onSubmit={handleSubmit(saveOrganization)} noValidate className="mt-6 space-y-4">
            <Field id="name" label="Organization name" error={errors.name?.message}>
              <Input
                id="name"
                autoFocus
                aria-invalid={!!errors.name}
                aria-describedby={errors.name ? "name-error" : undefined}
                {...register("name")}
              />
            </Field>
            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? <Loader2 className="animate-spin" /> : null}
              Continue <ArrowRight />
            </Button>
          </form>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="mt-8">
          <h1 className="text-2xl font-semibold tracking-tight">
            Where will you use verification?
          </h1>
          <p className="text-muted-foreground mt-2 text-sm">
            This tailors the threshold we recommend. Nothing is locked in.
          </p>

          <div className="mt-6 space-y-2">
            {USE_CASES.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setUseCase(option.value)}
                className={cn(
                  "focus-visible:ring-ring w-full rounded-lg border px-4 py-3 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none",
                  useCase === option.value
                    ? "border-primary bg-primary/5 font-medium"
                    : "hover:bg-accent",
                )}
                aria-pressed={useCase === option.value}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="mt-6 flex gap-3">
            <Button variant="outline" className="flex-1" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button className="flex-1" onClick={() => setStep(3)}>
              Continue <ArrowRight />
            </Button>
          </div>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="mt-8">
          <h1 className="text-2xl font-semibold tracking-tight">You&apos;re set up</h1>
          <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
            Create a test key in the console, then run this to create your first subject.
          </p>

          <div className="bg-card relative mt-5 rounded-lg border p-4">
            <pre className="overflow-x-auto font-mono text-[12px] leading-relaxed">
              {curlSample}
            </pre>
            <div className="absolute top-2 right-2">
              <CopyButton value={curlSample} />
            </div>
          </div>

          {/* Honest about the boundary: keys arrive in Phase 7. Pretending
              otherwise would send the user to a button that does not exist. */}
          <p className="text-muted-foreground mt-4 text-xs leading-relaxed">
            API key management ships in the next release. Until then the console shows your
            organization, members, and settings.
          </p>

          <Button className="mt-6 w-full" onClick={() => router.replace("/dashboard")}>
            Go to the console <ArrowRight />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
