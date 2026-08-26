"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import { ErrorState } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { ApiError, api } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { ThresholdSimulator } from "@/components/console/threshold-simulator";
import { Separator } from "@/components/ui/separator";

interface OrgSettings {
  match_threshold: number;
  threshold_preset: string;
  duplicate_check_enabled: boolean;
  duplicate_threshold: number;
  min_face_size_px: number;
  require_liveness: boolean;
  store_raw_images: boolean;
  image_retention_days: number;
  log_retention_days: number;
}

/**
 * Measured, not estimated.
 *
 * These FAR/FRR figures come from the Phase 0 calibration run over 8,559
 * genuine and 500,000 impostor LFW pairs. They are shown because a threshold
 * without its error rates is a number nobody can reason about — "stricter" tells
 * an operator nothing about how many real users it will lock out.
 *
 * `measured: false` on Strict is the honest part: its false-accept rate is
 * identical to Balanced's because 500,000 pairs cannot resolve a lower one.
 * Printing a smaller number there would be inventing precision we do not have.
 */
const PRESETS = [
  {
    value: "lenient",
    threshold: 0.32,
    label: "Lenient",
    detail: "High volume, low risk. Retail check-in, event entry.",
    far: 1.0e-5,
    frr: 0.0273,
    measured: true,
  },
  {
    value: "balanced",
    threshold: 0.38,
    label: "Balanced",
    detail: "The default. Suits most authentication flows.",
    far: 8.0e-6,
    frr: 0.0306,
    measured: true,
  },
  {
    value: "strict",
    threshold: 0.45,
    label: "Strict",
    detail: "Financial transactions, administrative access.",
    far: 8.0e-6,
    frr: 0.0421,
    measured: false,
  },
];

function formatFar(far: number): string {
  return `1 in ${Math.round(1 / far).toLocaleString()}`;
}

export default function SecuritySettingsPage() {
  const queryClient = useQueryClient();
  const organizationId = useAuthStore((state) => state.organization?.id ?? "");
  const can = useAuthStore((state) => state.can);
  // Threshold changes are Owner-only: it is the single dial that trades
  // security against usability for every verification in the tenant.
  const editable = can("threshold:update");

  const query = useQuery({
    queryKey: queryKeys.settings(organizationId),
    queryFn: () => api.get<OrgSettings>("/v1/console/organizations/current/settings"),
    enabled: !!organizationId,
  });

  const [threshold, setThreshold] = React.useState(0.38);
  React.useEffect(() => {
    if (query.data) setThreshold(Number(query.data.match_threshold));
  }, [query.data]);

  const save = useMutation({
    mutationFn: (payload: Partial<OrgSettings>) =>
      api.patch<OrgSettings>("/v1/console/organizations/current/settings", payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.settings(organizationId), updated);
      toast.success("Settings updated.");
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Could not save."),
  });

  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isLoading) {
    return (
      <Card className="space-y-4 p-6">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-9 w-full" />
      </Card>
    );
  }

  const matchedPreset = PRESETS.find((preset) => preset.threshold === threshold);
  const dirty = threshold !== Number(query.data?.match_threshold);

  return (
    <div className="space-y-4">
      <Card className="p-6">
        <h2 className="font-medium">Match threshold</h2>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
          The similarity a face must reach to be accepted. Raising it reduces false accepts and
          increases false rejects — there is no setting that reduces both.
        </p>

        <div className="mt-6 grid gap-2 sm:grid-cols-3">
          {PRESETS.map((preset) => (
            <button
              key={preset.value}
              type="button"
              disabled={!editable}
              onClick={() => setThreshold(preset.threshold)}
              className={cn(
                "focus-visible:ring-ring rounded-lg border p-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60",
                threshold === preset.threshold ? "border-primary bg-primary/5" : "hover:bg-accent",
              )}
            >
              <span className="flex items-baseline justify-between">
                <span className="text-sm font-medium">{preset.label}</span>
                <span className="font-mono text-xs tabular-nums">
                  {preset.threshold.toFixed(2)}
                </span>
              </span>
              <span className="text-muted-foreground mt-1 block text-xs leading-relaxed">
                {preset.detail}
              </span>
              <span className="text-muted-foreground mt-1.5 block text-[11px] tabular-nums">
                False accepts {formatFar(preset.far)}
                {preset.measured ? "" : "*"} · turns away {(preset.frr * 100).toFixed(2)}% of
                genuine users
              </span>
            </button>
          ))}
        </div>

        <div className="mt-6">
          <div className="flex items-baseline justify-between">
            <Label id="threshold-label">Custom value</Label>
            <span className="font-mono text-lg font-medium tabular-nums">
              {threshold.toFixed(3)}
            </span>
          </div>
          <Slider
            className="mt-3"
            min={0.2}
            max={0.8}
            step={0.005}
            value={[threshold]}
            onValueChange={([value]) => setThreshold(value ?? threshold)}
            disabled={!editable}
            aria-labelledby="threshold-label"
            aria-valuetext={`Match threshold ${threshold.toFixed(3)}${
              matchedPreset ? `, ${matchedPreset.label} preset` : ", custom"
            }`}
          />
          <div className="text-muted-foreground mt-2 flex justify-between text-xs">
            <span>0.20 — more accepts</span>
            <span>0.80 — more rejects</span>
          </div>
        </div>

        <div className="text-muted-foreground mt-4 space-y-1.5 text-xs leading-relaxed">
          <p>
            Rates measured on 8,559 genuine and 500,000 impostor pairs from a public benchmark. That
            benchmark is curated, frontal and well lit — expect your own population to be harder.
          </p>
          <p>
            * Strict measures the same false-accept rate as Balanced because 500,000 pairs cannot
            resolve a lower one. It is still defence in depth; its extra benefit is unmeasured
            rather than zero.
          </p>
          {!matchedPreset ? (
            <p className="text-warning font-medium">
              A custom threshold has no calibrated error rates. The figures above apply to the
              presets only.
            </p>
          ) : null}
        </div>

        <div className="border-warning/30 bg-warning/5 mt-6 flex gap-3 rounded-lg border p-4">
          <TriangleAlert className="text-warning mt-0.5 size-4 shrink-0" aria-hidden />
          <p className="text-muted-foreground text-sm leading-relaxed">
            Changing this affects every future verification. Existing sessions keep the threshold
            that was in force when they ran, so history stays auditable.
          </p>
        </div>

        {editable ? (
          <Button
            className="mt-4"
            disabled={!dirty || save.isPending}
            onClick={() =>
              save.mutate({
                match_threshold: threshold,
                threshold_preset: matchedPreset?.value ?? "custom",
              })
            }
          >
            {save.isPending ? (
              <>
                <Loader2 className="animate-spin" /> Saving…
              </>
            ) : (
              "Save threshold"
            )}
          </Button>
        ) : (
          <p className="text-muted-foreground mt-4 text-sm">
            Only an Owner can change the match threshold.
          </p>
        )}

        {/* Directly under the presets, because this is what turns choosing one
            from a guess into a decision. Rendered for every role: simulation is
            a read, and a compliance officer should be able to ask "what would
            this do" without being able to do it. */}
        <Separator className="my-6" />
        {/* The *saved* threshold, not the slider's pending value — the
            simulator's baseline must be what is live, or "would now be
            rejected" would be measured against a threshold nobody is using. */}
        <ThresholdSimulator current={Number(query.data?.match_threshold ?? 0.38)} />
      </Card>

      <Card className="p-6">
        <h2 className="font-medium">Data retention</h2>
        <dl className="mt-4 space-y-3 text-sm">
          <div className="flex items-center justify-between gap-4">
            <div>
              <dt className="font-medium">Store raw images</dt>
              <dd className="text-muted-foreground text-xs leading-relaxed">
                Off by default. Templates alone are enough to verify — retaining photographs is
                opt-in and increases your exposure.
              </dd>
            </div>
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
                query.data?.store_raw_images
                  ? "bg-warning/10 text-warning"
                  : "bg-success/10 text-success",
              )}
            >
              {query.data?.store_raw_images ? "enabled" : "disabled"}
            </span>
          </div>

          <div className="flex items-center justify-between gap-4 border-t pt-3">
            <dt className="text-muted-foreground">Log retention</dt>
            <dd className="font-mono text-xs tabular-nums">
              {query.data?.log_retention_days} days
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Duplicate detection</dt>
            <dd className="font-mono text-xs">
              {query.data?.duplicate_check_enabled
                ? `on · ${Number(query.data.duplicate_threshold).toFixed(2)}`
                : "off"}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Minimum face size</dt>
            <dd className="font-mono text-xs tabular-nums">{query.data?.min_face_size_px}px</dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}
