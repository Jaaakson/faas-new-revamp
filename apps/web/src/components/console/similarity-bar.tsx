"use client";

import { cn } from "@/lib/utils";

/**
 * Similarity against the threshold that was applied.
 *
 * A bare number ("0.81") means nothing without knowing what it had to beat, and
 * a bare verdict ("verified") throws away the margin. Showing both, with the
 * threshold marked in place, is what lets someone see *how close* a decision
 * was — which is the whole reason the confidence band exists.
 *
 * The scale starts at 0, not at the threshold. Zooming into the decision region
 * would exaggerate small differences and make a marginal pass look comfortable.
 */
export function SimilarityBar({
  similarity,
  threshold,
  decision,
  className,
  showScale = true,
}: {
  similarity: number | null;
  threshold: number;
  decision: string;
  className?: string;
  showScale?: boolean;
}) {
  // An inconclusive result has no similarity at all — there was nothing to
  // compare. Rendering a zero-width bar would imply a very poor match, which is
  // a different and wrong statement.
  if (similarity === null) {
    return (
      <div className={cn("space-y-1", className)}>
        <div className="bg-muted relative h-2 overflow-hidden rounded-full">
          <div
            className="absolute inset-y-0 w-px bg-slate-400"
            style={{ left: `${threshold * 100}%` }}
            aria-hidden
          />
        </div>
        <p className="text-muted-foreground text-[11px]">
          Not compared — threshold {threshold.toFixed(3)}
        </p>
      </div>
    );
  }

  const percent = Math.max(0, Math.min(100, similarity * 100));
  const verified = decision === "verified";

  return (
    <div className={cn("space-y-1", className)}>
      <div
        className="bg-muted relative h-2 overflow-hidden rounded-full"
        role="meter"
        aria-label="Similarity against threshold"
        aria-valuenow={Number(similarity.toFixed(3))}
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuetext={`${similarity.toFixed(3)} against a threshold of ${threshold.toFixed(3)}`}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-300",
            verified ? "bg-emerald-500" : "bg-amber-500",
          )}
          style={{ width: `${percent}%` }}
        />
        {/* The threshold marker sits above the fill so it stays visible even
            when the bar passes it. */}
        <div
          className="absolute inset-y-0 w-0.5 bg-slate-700 dark:bg-slate-200"
          style={{ left: `${Math.min(100, threshold * 100)}%` }}
          aria-hidden
        />
      </div>

      {showScale ? (
        <div className="text-muted-foreground flex items-baseline justify-between text-[11px] tabular-nums">
          <span className={cn("font-medium", verified ? "text-emerald-600" : "text-amber-600")}>
            {similarity.toFixed(4)}
          </span>
          <span>threshold {threshold.toFixed(3)}</span>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The confidence band, as a word plus what it is for.
 *
 * `low` on a $50,000 transfer is exactly where a customer should trigger a
 * second factor, so the band is labelled with that use rather than left as an
 * unexplained adjective.
 */
export function ConfidenceBadge({ confidence }: { confidence: string | null }) {
  if (!confidence) return null;

  const copy = {
    high: { label: "High confidence", hint: "Comfortable margin above the threshold." },
    medium: { label: "Medium confidence", hint: "A modest margin." },
    low: {
      label: "Low confidence",
      hint: "Verified, but marginal — a good place to require a second factor.",
    },
  }[confidence];

  if (!copy) return null;

  return (
    <span
      title={copy.hint}
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        confidence === "high" && "bg-emerald-500/10 text-emerald-600",
        confidence === "medium" && "bg-blue-500/10 text-blue-600",
        confidence === "low" && "bg-amber-500/10 text-amber-600",
      )}
    >
      {copy.label}
    </span>
  );
}
