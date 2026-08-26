"use client";

import * as React from "react";
import { motion, useReducedMotion } from "motion/react";
import { CircleCheck } from "lucide-react";

const SIMILARITY = 0.8121;
const THRESHOLD = 0.38;

/**
 * The hero's product-truth panel: an actual verification decision object.
 *
 * A screenshot of a dashboard says "there is a dashboard". A decision with its
 * score, the threshold it was measured against, and the latency says what the
 * product *does* — in about two seconds, and without a single claim we would
 * have to defend later. Every number here matches the API contract in
 * docs/07-api-design.md §3.3.
 */
export function VerificationResultCard() {
  const reduced = useReducedMotion();

  // The gauge sweeps to position on mount only. Under reduced motion it starts
  // at its final value, which is the same information without the movement.
  const markerLeft = `${SIMILARITY * 100}%`;
  const thresholdLeft = `${THRESHOLD * 100}%`;

  return (
    <div className="bg-card w-full rounded-xl border p-5 shadow-lg">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <CircleCheck className="text-success size-5" aria-hidden />
          <span className="text-success text-sm font-semibold tracking-wide uppercase">
            Verified
          </span>
        </div>
        <code className="text-muted-foreground font-mono text-xs">vs_01HQZX8K…</code>
      </div>

      <div className="mt-5">
        <div className="text-muted-foreground flex items-baseline justify-between text-xs">
          <span>Similarity</span>
          <span className="text-foreground font-mono text-lg font-medium tabular-nums">
            {SIMILARITY.toFixed(4)}
          </span>
        </div>

        {/* The signature control: a bar with a threshold tick, not a bare
            number. A number makes the reader recall the threshold; a tick shows
            the margin at a glance. */}
        <div className="bg-muted relative mt-2 h-2 w-full overflow-visible rounded-full">
          <motion.div
            className="bg-success h-full rounded-full"
            initial={reduced ? { width: markerLeft } : { width: 0 }}
            animate={{ width: markerLeft }}
            transition={{ duration: reduced ? 0 : 0.9, ease: "easeOut", delay: reduced ? 0 : 0.3 }}
          />
          <div
            className="bg-foreground absolute -top-1 h-4 w-px"
            style={{ left: thresholdLeft }}
            aria-hidden
          />
        </div>

        <div className="text-muted-foreground mt-2 flex justify-between text-[11px]">
          <span>0.0</span>
          <span className="font-mono">threshold {THRESHOLD.toFixed(2)}</span>
          <span>1.0</span>
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-3 gap-3 border-t pt-4 text-xs">
        <div>
          <dt className="text-muted-foreground">Latency</dt>
          <dd className="mt-0.5 font-mono tabular-nums">284 ms</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Templates</dt>
          <dd className="mt-0.5 font-mono tabular-nums">3</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Confidence</dt>
          <dd className="mt-0.5 font-mono">high</dd>
        </div>
      </dl>
    </div>
  );
}
