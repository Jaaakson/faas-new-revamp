"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, Check, HelpCircle, RotateCcw, ShieldX, Timer, X } from "lucide-react";

import { CameraCapture } from "@/components/console/camera-capture";
import { PageHeader } from "@/components/console/page-header";
import { ConfidenceBadge, SimilarityBar } from "@/components/console/similarity-bar";
import { EmptyState, ErrorState } from "@/components/console/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useSubjects } from "@/features/analytics/api";
import {
  DECISION_COPY,
  type VerificationResult,
  failureLabel,
  useThresholdInfo,
  useVerify,
} from "@/features/verification/api";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

/**
 * The live test page.
 *
 * Its job is to make the product's central claim inspectable: capture a face,
 * see the decision, and see *why* — the similarity against the threshold, the
 * confidence margin, and where the milliseconds went. An integrator who can
 * reproduce a rejection here stops filing tickets about it.
 */
export default function VerifyPage() {
  const [subjectId, setSubjectId] = React.useState("");
  const [result, setResult] = React.useState<VerificationResult | null>(null);

  const verify = useVerify();
  const threshold = useThresholdInfo();
  // Only enrolled subjects can be verified; offering the others would produce a
  // guaranteed `subject_not_enrolled` and teach the user nothing.
  const subjects = useSubjects({ status: "enrolled", limit: 50 });

  // Memoised: a fresh `[]` on every render would retrigger the effect below
  // forever, since its identity changes even when the data does not.
  const rows = React.useMemo(() => subjects.data?.data ?? [], [subjects.data]);

  React.useEffect(() => {
    if (!subjectId && rows.length > 0) setSubjectId(rows[0]!.id);
  }, [rows, subjectId]);

  const run = React.useCallback(
    (dataUrl: string) => {
      if (!subjectId) return;
      setResult(null);
      verify.mutate(
        { subject_id: subjectId, image: dataUrl },
        { onSuccess: (value) => setResult(value) },
      );
    },
    [subjectId, verify],
  );

  const selected = rows.find((row) => row.id === subjectId);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Live verification"
        description="Capture a face and see the decision, the margin, and where the time went."
      />

      {subjects.isError ? (
        <ErrorState error={subjects.error} onRetry={() => void subjects.refetch()} />
      ) : subjects.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={HelpCircle}
          title="No enrolled subjects yet"
          description="Verification compares a face against an enrolled profile. Enroll someone first, then come back."
          action={
            <Button asChild size="sm">
              <Link href="/dashboard/subjects">Go to subjects</Link>
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="space-y-4 p-5">
            <div className="space-y-1.5">
              <Label htmlFor="subject">Verify against</Label>
              <select
                id="subject"
                value={subjectId}
                onChange={(event) => {
                  setSubjectId(event.target.value);
                  setResult(null);
                }}
                className="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
              >
                {rows.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.display_name ? `${row.display_name} — ` : ""}
                    {row.external_id}
                  </option>
                ))}
              </select>
              {threshold.data ? (
                <p className="text-muted-foreground text-xs">
                  Threshold {threshold.data.threshold.toFixed(3)} ({threshold.data.preset})
                  {threshold.data.measured && threshold.data.frr !== null
                    ? ` · measured FRR ${(threshold.data.frr * 100).toFixed(2)}%`
                    : " · not calibrated"}
                </p>
              ) : null}
            </div>

            <Separator />

            <CameraCapture
              prompt="Look straight at the camera."
              onCapture={run}
              disabled={verify.isPending || !subjectId}
              autoCapture={false}
            />
            <p className="text-muted-foreground text-xs">
              Auto-capture is off here on purpose — you decide when to submit, so you can
              deliberately test a bad frame.
            </p>
          </Card>

          <Card className="p-5">
            <h2 className="text-sm font-medium">Result</h2>
            <Separator className="my-3" />

            {verify.isPending ? (
              <div className="space-y-3 py-4">
                <Skeleton className="h-8 w-40" />
                <Skeleton className="h-2 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            ) : verify.isError ? (
              <RequestFailure error={verify.error} />
            ) : result ? (
              <ResultPanel result={result} subjectLabel={selected?.external_id ?? subjectId} />
            ) : (
              <p className="text-muted-foreground py-8 text-center text-xs">
                Capture a frame to run a verification.
              </p>
            )}

            {result || verify.isError ? (
              <Button
                variant="ghost"
                size="sm"
                className="mt-4 w-full"
                onClick={() => {
                  setResult(null);
                  verify.reset();
                }}
              >
                <RotateCcw className="size-3.5" aria-hidden />
                Clear
              </Button>
            ) : null}
          </Card>
        </div>
      )}
    </div>
  );
}

function ResultPanel({
  result,
  subjectLabel,
}: {
  result: VerificationResult;
  subjectLabel: string;
}) {
  const copy = DECISION_COPY[result.decision];
  const tone = {
    verified: "border-emerald-500/30 bg-emerald-500/5",
    rejected: "border-amber-500/30 bg-amber-500/5",
    inconclusive: "border-slate-500/30 bg-slate-500/5",
    error: "border-destructive/30 bg-destructive/5",
  }[result.decision];

  const Icon = {
    verified: Check,
    rejected: X,
    inconclusive: HelpCircle,
    error: ShieldX,
  }[result.decision];

  return (
    <div className="space-y-4">
      <div className={cn("flex items-start gap-3 rounded-lg border px-3.5 py-3", tone)}>
        <Icon
          className={cn(
            "mt-0.5 size-4 shrink-0",
            result.decision === "verified" && "text-emerald-600",
            result.decision === "rejected" && "text-amber-600",
            result.decision === "inconclusive" && "text-slate-500",
            result.decision === "error" && "text-destructive",
          )}
          aria-hidden
        />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium">{copy?.label ?? result.decision}</p>
            <ConfidenceBadge confidence={result.confidence} />
            {result.failure_reason ? (
              <Badge variant="outline">{failureLabel(result.failure_reason)}</Badge>
            ) : null}
          </div>
          <p className="text-muted-foreground mt-0.5 text-xs">{result.guidance ?? copy?.blurb}</p>
        </div>
      </div>

      <SimilarityBar
        similarity={result.similarity}
        threshold={result.threshold}
        decision={result.decision}
      />

      <dl className="grid grid-cols-2 gap-3 text-xs">
        <Field label="Subject" value={subjectLabel} />
        <Field label="Templates compared" value={String(result.templates_compared)} />
      </dl>

      <div>
        <p className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-[11px] font-medium">
          <Timer className="size-3" aria-hidden />
          Where the time went
        </p>
        <TimingBar timing={result.timing} />
      </div>

      {result.quality ? (
        <div>
          <p className="text-muted-foreground mb-1.5 text-[11px] font-medium">Capture quality</p>
          <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <Field label="Score" value={`${(result.quality.score * 100).toFixed(0)}%`} />
            <Field label="Sharpness" value={result.quality.sharpness.toFixed(2)} />
            <Field label="Face size" value={`${result.quality.face_size_px.toFixed(0)} px`} />
            <Field label="Yaw" value={`${result.quality.pose.yaw.toFixed(1)}°`} />
          </dl>
        </div>
      ) : null}

      {result.liveness?.evaluated ? (
        <div>
          <p className="text-muted-foreground mb-1.5 text-[11px] font-medium">
            Liveness signals — heuristics, not certified PAD
          </p>
          <ul className="space-y-1">
            {result.liveness.signals.map((signal) => (
              <li key={signal.signal} className="flex items-center gap-2 text-xs">
                {signal.passed ? (
                  <Check className="size-3 text-emerald-500" aria-hidden />
                ) : (
                  <AlertTriangle className="size-3 text-amber-500" aria-hidden />
                )}
                <span className="text-muted-foreground">{signal.signal.replace(/_/g, " ")}</span>
                <span className="ml-auto tabular-nums">{signal.score.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <Button asChild variant="outline" size="sm" className="w-full">
        <Link href={`/dashboard/verifications?highlight=${result.id}`}>
          View in the verification log
        </Link>
      </Button>
    </div>
  );
}

/** Proportional segments, so a slow stage is visible rather than merely listed. */
function TimingBar({ timing }: { timing: VerificationResult["timing"] }) {
  const stages = [
    { label: "detect", value: timing.detect_ms ?? 0, className: "bg-blue-500" },
    { label: "embed", value: timing.embed_ms ?? 0, className: "bg-indigo-500" },
    { label: "match", value: timing.match_ms ?? 0, className: "bg-violet-500" },
  ];
  const measured = stages.reduce((total, stage) => total + stage.value, 0);
  const other = Math.max(0, timing.total_ms - measured);
  const total = Math.max(1, timing.total_ms);

  return (
    <div className="space-y-1.5">
      <div className="bg-muted flex h-2 overflow-hidden rounded-full">
        {stages.map((stage) => (
          <div
            key={stage.label}
            className={stage.className}
            style={{ width: `${(stage.value / total) * 100}%` }}
            title={`${stage.label} ${stage.value} ms`}
          />
        ))}
        <div
          className="bg-slate-300 dark:bg-slate-600"
          style={{ width: `${(other / total) * 100}%` }}
          title={`other ${other} ms`}
        />
      </div>
      <div className="text-muted-foreground flex flex-wrap gap-x-3 text-[11px] tabular-nums">
        {stages.map((stage) => (
          <span key={stage.label}>
            {stage.label} {stage.value}ms
          </span>
        ))}
        <span>other {other}ms</span>
        <span className="ml-auto font-medium">total {timing.total_ms}ms</span>
      </div>
    </div>
  );
}

/**
 * A *request* failure, which is a different thing from a rejected verification.
 * Quota exhaustion is the case worth naming explicitly, because the fix is
 * commercial rather than technical.
 */
function RequestFailure({ error }: { error: unknown }) {
  const quota = error instanceof ApiError && error.status === 429;

  return (
    <div className="border-destructive/30 bg-destructive/5 flex gap-3 rounded-lg border px-3.5 py-3">
      <AlertTriangle className="text-destructive mt-0.5 size-4 shrink-0" aria-hidden />
      <div>
        <p className="text-sm font-medium">
          {quota ? "Quota or rate limit reached" : "The request failed"}
        </p>
        <p className="text-muted-foreground mt-0.5 text-xs">
          {error instanceof Error ? error.message : "Something went wrong."}
        </p>
        {quota ? (
          <p className="text-muted-foreground mt-1.5 text-xs">
            This is not a verification outcome — nothing was decided and nothing was charged.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-[11px]">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}
