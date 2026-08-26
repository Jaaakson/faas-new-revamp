"use client";

import { CircleCheck, CircleX, TriangleAlert, Zap } from "lucide-react";

import { cn } from "@/lib/utils";

const DECISIONS = {
  verified: { icon: CircleCheck, label: "verified", tone: "text-success bg-success/10" },
  rejected: { icon: CircleX, label: "rejected", tone: "text-destructive bg-destructive/10" },
  inconclusive: {
    icon: TriangleAlert,
    label: "inconclusive",
    tone: "text-warning bg-warning/10",
  },
  error: { icon: Zap, label: "error", tone: "text-muted-foreground bg-muted" },
} as const;

export type Decision = keyof typeof DECISIONS;

/**
 * A decision badge.
 *
 * Colour is never the only signal — each decision pairs its colour with a
 * distinct icon, so meaning survives colour-vision deficiency and the
 * grayscale screenshot that ends up in a slide deck.
 */
export function DecisionBadge({ decision }: { decision: string }) {
  const config = DECISIONS[decision as Decision] ?? DECISIONS.error;
  const Icon = config.icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        config.tone,
      )}
    >
      <Icon className="size-3" aria-hidden />
      {config.label}
    </span>
  );
}

/**
 * The console's signature control: a score bar with a threshold tick.
 *
 * A bare number makes the reader recall the threshold before they can judge it.
 * A bar with a tick shows the margin at a glance — which is what turns a log
 * table into an instrument (docs/03-user-flows-wireframes.md §B4).
 */
export function SimilarityBar({
  similarity,
  threshold,
  decision,
  showValue = true,
  className,
}: {
  similarity: number | null;
  threshold: number;
  decision: string;
  showValue?: boolean;
  className?: string;
}) {
  if (similarity === null) {
    // No comparison happened — a dash is honest, a zero-width bar is a lie.
    return <span className="text-muted-foreground font-mono text-xs">—</span>;
  }

  const tone =
    decision === "verified"
      ? "bg-success"
      : decision === "rejected"
        ? "bg-destructive"
        : "bg-warning";

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        className="bg-muted relative h-1.5 w-20 shrink-0 rounded-full"
        role="img"
        aria-label={`Similarity ${similarity.toFixed(3)}, threshold ${threshold.toFixed(2)}`}
      >
        <div
          className={cn("h-full rounded-full", tone)}
          style={{ width: `${Math.min(100, Math.max(0, similarity * 100))}%` }}
        />
        <div
          className="bg-foreground absolute -top-1 h-3.5 w-px"
          style={{ left: `${threshold * 100}%` }}
          aria-hidden
        />
      </div>
      {showValue ? (
        <span className="text-muted-foreground font-mono text-xs tabular-nums">
          {similarity.toFixed(3)}
        </span>
      ) : null}
    </div>
  );
}

export function ConfidenceBadge({ confidence }: { confidence: string | null }) {
  if (!confidence) return null;

  const tone =
    confidence === "high"
      ? "text-success"
      : confidence === "medium"
        ? "text-muted-foreground"
        : "text-warning";

  return <span className={cn("text-xs font-medium", tone)}>{confidence}</span>;
}
