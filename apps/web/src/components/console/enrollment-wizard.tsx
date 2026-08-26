"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, Check, RotateCcw, ShieldAlert } from "lucide-react";

import { CameraCapture } from "@/components/console/camera-capture";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  type EnrollmentImageResult,
  type EnrollmentResponse,
  gateLabel,
  useEnroll,
} from "@/features/biometrics/api";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

/**
 * Three shots, each with a slightly different head position.
 *
 * The variation is deliberate and it is mild. Templates that cover a small
 * range of angles make matching robust to how someone happens to stand at a
 * turnstile; angles beyond about 25° fail the pose gate, so "slightly" is the
 * operative word in every prompt. Asking for a dramatic turn would produce
 * three rejected frames and a confused user.
 */
const SHOTS = [
  { prompt: "Look straight at the camera.", hint: "Neutral expression, eyes open." },
  {
    prompt: "Turn your head slightly to the left.",
    hint: "Just a small turn — stay facing forward.",
  },
  { prompt: "Turn your head slightly to the right.", hint: "Same again, the other way." },
] as const;

interface EnrollmentWizardProps {
  subjectId: string;
  subjectLabel: string;
  /** True when a profile already exists — enrolling will supersede it. */
  hasExistingProfile?: boolean;
  onComplete?: (result: EnrollmentResponse) => void;
  onCancel?: () => void;
}

type Phase = "capture" | "review" | "done";

export function EnrollmentWizard({
  subjectId,
  subjectLabel,
  hasExistingProfile = false,
  onComplete,
  onCancel,
}: EnrollmentWizardProps) {
  const [shots, setShots] = React.useState<string[]>([]);
  const [phase, setPhase] = React.useState<Phase>("capture");
  const [result, setResult] = React.useState<EnrollmentResponse | null>(null);
  const enroll = useEnroll();

  const index = shots.length;
  // Clamped rather than indexed directly: `shots.length` reaches SHOTS.length
  // on the last capture, one past the end.
  const current = SHOTS[Math.min(index, SHOTS.length - 1)] ?? SHOTS[0];

  /**
   * Per-frame feedback from the *last* rejected attempt, keyed by index.
   *
   * This is what turns a failure into a retake rather than a dead end: the
   * server said frame 1 was too dark, so frame 1's prompt says so while it is
   * being recaptured.
   */
  const [frameFeedback, setFrameFeedback] = React.useState<Record<number, string>>({});

  const handleCapture = React.useCallback((dataUrl: string) => {
    setShots((previous) => (previous.length >= SHOTS.length ? previous : [...previous, dataUrl]));
  }, []);

  React.useEffect(() => {
    if (shots.length >= SHOTS.length) setPhase("review");
  }, [shots.length]);

  const retake = (position: number) => {
    setShots((previous) => previous.filter((_, i) => i !== position));
    setPhase("capture");
  };

  const submit = async () => {
    setFrameFeedback({});
    try {
      const response = await enroll.mutateAsync({
        subject_id: subjectId,
        images: shots,
        options: { replace_existing: true },
      });
      setResult(response);
      setPhase("done");
      onComplete?.(response);
    } catch (cause) {
      if (cause instanceof ApiError) {
        const images = cause.details?.images as EnrollmentImageResult[] | undefined;
        if (Array.isArray(images)) {
          const feedback: Record<number, string> = {};
          for (const image of images) {
            if (!image.accepted && image.guidance) feedback[image.index] = image.guidance;
          }
          setFrameFeedback(feedback);
          // Drop only the frames the server actually rejected. Making someone
          // recapture three shots because one was blurred is the difference
          // between a 20-second flow and an abandoned one.
          setShots((previous) => previous.filter((_, i) => !feedback[i]));
          setPhase("capture");
        }
      }
    }
  };

  if (phase === "done" && result) {
    return <EnrollmentSuccess result={result} subjectId={subjectId} />;
  }

  const duplicate = duplicateFrom(enroll.error);

  return (
    <div className="space-y-5">
      <StepIndicator captured={shots.length} total={SHOTS.length} />

      {hasExistingProfile && phase === "capture" ? (
        <Notice tone="warning" icon={AlertTriangle} title="This will replace the current profile">
          The existing profile is kept as history and marked superseded. Its templates are
          destroyed, so it can no longer be used to verify.
        </Notice>
      ) : null}

      {duplicate ? (
        <Notice tone="danger" icon={ShieldAlert} title="This face is already enrolled">
          <p>
            It matches{" "}
            <Link
              href={`/dashboard/subjects/${duplicate.matched_subject_id}`}
              className="font-medium underline underline-offset-2"
            >
              another subject
            </Link>{" "}
            at {(duplicate.similarity * 100).toFixed(1)}% similarity, above your{" "}
            {(duplicate.threshold * 100).toFixed(0)}% duplicate threshold.
          </p>
          <p className="mt-1.5">
            If this is genuinely a different person — identical twins do exist — enroll them through
            the API with <code className="text-[11px]">check_duplicates: false</code>.
          </p>
        </Notice>
      ) : null}

      {enroll.isError && !duplicate && !Object.keys(frameFeedback).length ? (
        <Notice tone="danger" icon={AlertTriangle} title="Enrollment failed">
          {enroll.error instanceof Error ? enroll.error.message : "Something went wrong."}
        </Notice>
      ) : null}

      {phase === "capture" ? (
        <>
          <CameraCapture
            key={index}
            prompt={current.prompt}
            serverHint={frameFeedback[index] ?? null}
            onCapture={handleCapture}
            disabled={enroll.isPending}
          />
          <p className="text-muted-foreground text-xs">{current.hint}</p>
        </>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            {shots.map((shot, position) => (
              <figure key={position} className="space-y-2">
                {/* Local data URLs of the operator's own capture; next/image
                    would add a proxy hop for no benefit. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={shot}
                  alt={`Capture ${position + 1}: ${SHOTS[position]?.prompt ?? ""}`}
                  className="aspect-[4/3] w-full rounded-lg border object-cover"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full"
                  onClick={() => retake(position)}
                  disabled={enroll.isPending}
                >
                  <RotateCcw className="size-3.5" aria-hidden />
                  Retake
                </Button>
              </figure>
            ))}
          </div>

          <div className="flex items-center justify-between gap-3 border-t pt-4">
            <p className="text-muted-foreground text-xs">
              Enrolling {subjectLabel}. Frames are analysed and discarded — only the resulting
              mathematical templates are stored.
            </p>
            <div className="flex shrink-0 gap-2">
              {onCancel ? (
                <Button variant="ghost" onClick={onCancel} disabled={enroll.isPending}>
                  Cancel
                </Button>
              ) : null}
              <Button onClick={() => void submit()} disabled={enroll.isPending}>
                {enroll.isPending ? "Enrolling…" : "Enroll face"}
                {!enroll.isPending ? <ArrowRight className="size-4" aria-hidden /> : null}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StepIndicator({ captured, total }: { captured: number; total: number }) {
  return (
    <ol className="flex items-center gap-2" aria-label="Capture progress">
      {Array.from({ length: total }, (_, position) => {
        const done = position < captured;
        const active = position === captured;
        return (
          <li key={position} className="flex flex-1 items-center gap-2">
            <span
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-medium transition-colors",
                done
                  ? "border-emerald-500 bg-emerald-500 text-white"
                  : active
                    ? "border-primary text-primary"
                    : "border-muted-foreground/30 text-muted-foreground",
              )}
              aria-current={active ? "step" : undefined}
            >
              {done ? <Check className="size-3.5" aria-hidden /> : position + 1}
            </span>
            <span className="sr-only">
              {SHOTS[position]?.prompt} {done ? "captured" : active ? "current" : "pending"}
            </span>
            {position < total - 1 ? (
              <span
                className={cn("h-px flex-1", done ? "bg-emerald-500" : "bg-border")}
                aria-hidden
              />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function EnrollmentSuccess({
  result,
  subjectId,
}: {
  result: EnrollmentResponse;
  subjectId: string;
}) {
  const profile = result.face_profile;
  return (
    <div className="space-y-5">
      <div className="flex flex-col items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-6 py-8 text-center">
        <div className="flex size-10 items-center justify-center rounded-full bg-emerald-500 text-white">
          <Check className="size-5" aria-hidden />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-medium">Face enrolled</p>
          <p className="text-muted-foreground text-xs">
            Profile v{profile?.version} · {profile?.template_count} templates · completed in{" "}
            {result.latency_ms} ms
          </p>
        </div>
        <Button asChild size="sm" className="mt-1">
          <Link href={`/dashboard/subjects/${subjectId}`}>View subject</Link>
        </Button>
      </div>

      <div className="space-y-2">
        <p className="text-muted-foreground text-xs font-medium">Per-frame quality</p>
        <div className="divide-y rounded-lg border">
          {result.images.map((image) => (
            <ImageResultRow key={image.index} image={image} />
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * One frame's outcome. Shown on success as well as failure — an integrator
 * tuning their capture UI needs to see which frame was weakest even when the
 * batch succeeded.
 */
export function ImageResultRow({ image }: { image: EnrollmentImageResult }) {
  const failed = image.checks.filter((check) => !check.passed);

  return (
    <div className="flex items-center gap-3 px-3 py-2.5 text-xs">
      <span className="text-muted-foreground w-12 shrink-0 font-mono">#{image.index + 1}</span>
      <Badge variant={image.accepted ? "success" : "destructive"}>
        {image.accepted ? "accepted" : "rejected"}
      </Badge>
      <span className="tabular-nums">{(image.quality_score * 100).toFixed(0)}%</span>
      <span className="text-muted-foreground truncate">
        {image.guidance ??
          (failed.length
            ? failed.map((check) => gateLabel(check.check)).join(", ")
            : "All checks passed")}
      </span>
    </div>
  );
}

function Notice({
  tone,
  icon: Icon,
  title,
  children,
}: {
  tone: "warning" | "danger";
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-lg border px-3.5 py-3 text-xs leading-relaxed",
        tone === "danger"
          ? "border-destructive/30 bg-destructive/5 text-destructive-foreground"
          : "border-amber-500/30 bg-amber-500/5",
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 size-4 shrink-0",
          tone === "danger" ? "text-destructive" : "text-amber-500",
        )}
      />
      <div>
        <p className="font-medium">{title}</p>
        <div className="text-muted-foreground mt-0.5">{children}</div>
      </div>
    </div>
  );
}

interface DuplicateDetails {
  matched_subject_id: string;
  similarity: number;
  threshold: number;
}

function duplicateFrom(error: unknown): DuplicateDetails | null {
  if (!(error instanceof ApiError) || error.code !== "duplicate_face_detected") return null;
  const details = error.details as Partial<DuplicateDetails> | undefined;
  if (!details?.matched_subject_id) return null;
  return {
    matched_subject_id: details.matched_subject_id,
    similarity: details.similarity ?? 0,
    threshold: details.threshold ?? 0,
  };
}
