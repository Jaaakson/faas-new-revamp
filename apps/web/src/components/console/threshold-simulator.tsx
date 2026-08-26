"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, BookOpen, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { useThresholdSimulation } from "@/features/verification/api";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * "What would this threshold have done to my traffic?"
 *
 * The published FAR/FRR figures come from a public benchmark that is easier than
 * production. This answers the same question against the customer's own recorded
 * decisions, which is the number that actually applies to them.
 *
 * The two outcomes are deliberately not summed into one score. Newly *rejected*
 * is a usability cost paid by real users; newly *accepted* is a security cost.
 * They are not interchangeable and a single "impact" number would imply they are.
 */
export function ThresholdSimulator({ current }: { current: number }) {
  const [candidate, setCandidate] = React.useState(current);
  const [days, setDays] = React.useState(30);

  // Debounced so dragging does not fire a request per pixel, but short enough
  // that the numbers feel attached to the handle.
  const [debounced, setDebounced] = React.useState(current);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(candidate), 180);
    return () => clearTimeout(timer);
  }, [candidate]);

  React.useEffect(() => setCandidate(current), [current]);

  const query = useThresholdSimulation(debounced, days);
  const data = query.data;
  const changed = Math.abs(candidate - current) > 0.0001;

  return (
    <section className="space-y-4" aria-labelledby="simulator-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="simulator-heading" className="text-sm font-medium">
            Threshold simulator
          </h3>
          <p className="text-muted-foreground mt-0.5 text-xs">
            Replays your recorded verifications against a candidate threshold. No new inference runs
            — the decisions were stored with the threshold that produced them.
          </p>
        </div>
        <div className="flex shrink-0 gap-1">
          {[7, 30, 90].map((option) => (
            <Button
              key={option}
              variant={days === option ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setDays(option)}
              aria-pressed={days === option}
            >
              {option}d
            </Button>
          ))}
        </div>
      </div>

      {/* ── The control ─────────────────────────────────────────────────────── */}
      <div className="bg-card rounded-lg border p-5">
        <div className="flex items-baseline justify-between">
          <span className="text-muted-foreground text-xs">Candidate threshold</span>
          <div className="flex items-baseline gap-2 tabular-nums">
            <span className="text-2xl font-semibold tracking-tight">{candidate.toFixed(3)}</span>
            {changed ? (
              <span className="text-muted-foreground text-xs">from {current.toFixed(3)}</span>
            ) : (
              <Badge variant="outline">current</Badge>
            )}
          </div>
        </div>

        <div className="mt-4">
          <Slider
            value={[candidate]}
            onValueChange={([value]) => setCandidate(value ?? current)}
            min={0.2}
            max={0.8}
            step={0.005}
            aria-label="Candidate threshold"
          />
          <div className="text-muted-foreground mt-1.5 flex justify-between text-[11px]">
            <span>0.20 — more accepts, more false accepts</span>
            <span>0.80 — fewer accepts, more lockouts</span>
          </div>
        </div>

        <Histogram
          buckets={data?.histogram ?? []}
          candidate={candidate}
          current={current}
          loading={query.isLoading}
        />
      </div>

      {/* ── The consequence ─────────────────────────────────────────────────── */}
      {query.isLoading && !data ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <ImpactCard
              tone="danger"
              icon={TrendingDown}
              value={data.newly_rejected}
              label="would now be rejected"
              blurb="Real people who were verified and would have been turned away."
              total={data.original_verified}
            />
            <ImpactCard
              tone="warning"
              icon={TrendingUp}
              value={data.newly_accepted}
              label="would now be accepted"
              blurb="Decisions that were refused and would have been let through."
              total={data.original_rejected}
            />
          </div>

          <div className="bg-card rounded-lg border p-5">
            <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
              <Stat label="Comparable sessions" value={data.comparable.toLocaleString()} />
              <Stat label="Unchanged" value={data.unchanged.toLocaleString()} />
              <div>
                <p className="text-muted-foreground text-xs">Acceptance rate</p>
                <p className="mt-0.5 flex items-center gap-1.5 text-sm font-medium tabular-nums">
                  {(data.acceptance_rate_before * 100).toFixed(1)}%
                  <ArrowRight className="text-muted-foreground size-3.5" aria-hidden />
                  <span className={cn(changed && "text-primary")}>
                    {(data.acceptance_rate_after * 100).toFixed(1)}%
                  </span>
                </p>
              </div>
            </div>

            <p className="text-muted-foreground mt-4 text-xs leading-relaxed">
              <ShieldCheck className="mr-1 inline size-3.5 align-[-2px]" aria-hidden />
              <strong>Inconclusive sessions are excluded.</strong> The pipeline stopped before
              matching, so no threshold would have changed them — counting them would make this look
              more decisive than it is.
            </p>
          </div>

          {data.examples.length > 0 ? (
            <FlippedSessions examples={data.examples} candidate={candidate} />
          ) : changed ? (
            <p className="text-muted-foreground rounded-lg border border-dashed py-8 text-center text-sm">
              No recorded decision would change at {candidate.toFixed(3)}.
            </p>
          ) : null}
        </>
      ) : null}

      <Separator />

      <div className="text-muted-foreground flex items-start gap-2 text-xs leading-relaxed">
        <BookOpen className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        <p>
          The FAR/FRR figures beside each preset come from LFW — a curated public benchmark that is
          easier than production, and demographically skewed. Treat them as an upper bound.{" "}
          <Link
            href="/docs/model-card"
            className="hover:text-foreground font-medium underline underline-offset-2"
          >
            Read the model card
          </Link>{" "}
          for what was measured and what was not.
        </p>
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="mt-0.5 text-sm font-medium tabular-nums">{value}</p>
    </div>
  );
}

function ImpactCard({
  tone,
  icon: Icon,
  value,
  label,
  blurb,
  total,
}: {
  tone: "danger" | "warning";
  icon: React.ComponentType<{ className?: string }>;
  value: number;
  label: string;
  blurb: string;
  total: number;
}) {
  const share = total > 0 ? (value / total) * 100 : 0;
  const muted = value === 0;

  return (
    <div
      className={cn(
        "rounded-lg border p-5 transition-colors",
        muted
          ? "bg-card"
          : tone === "danger"
            ? "border-destructive/30 bg-destructive/5"
            : "border-amber-500/30 bg-amber-500/5",
      )}
    >
      <div className="flex items-center gap-2">
        <Icon
          className={cn(
            "size-4",
            muted
              ? "text-muted-foreground"
              : tone === "danger"
                ? "text-destructive"
                : "text-amber-500",
          )}
        />
        <span className="text-muted-foreground text-xs">{label}</span>
      </div>
      <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">
        {value.toLocaleString()}
      </p>
      {!muted ? (
        <p className="text-muted-foreground mt-0.5 text-xs tabular-nums">
          {share.toFixed(1)}% of {total.toLocaleString()}
        </p>
      ) : null}
      <p className="text-muted-foreground mt-2 text-xs leading-relaxed">{blurb}</p>
    </div>
  );
}

/**
 * Similarity distribution with the threshold drawn through it.
 *
 * The bare number cannot show whether you are about to move the threshold
 * through a dense part of your traffic or an empty one — and that difference is
 * the entire decision.
 */
function Histogram({
  buckets,
  candidate,
  current,
  loading,
}: {
  buckets: { from: number; to: number; count: number }[];
  candidate: number;
  current: number;
  loading: boolean;
}) {
  if (loading && buckets.length === 0) {
    return <Skeleton className="mt-5 h-20 w-full" />;
  }
  if (buckets.length === 0) return null;

  const max = Math.max(...buckets.map((b) => b.count), 1);

  return (
    <div className="mt-5">
      <p className="text-muted-foreground mb-2 text-[11px]">Where your traffic actually sits</p>
      <div
        className="relative flex h-20 items-end gap-px"
        role="img"
        aria-label={`Similarity distribution with the candidate threshold at ${candidate.toFixed(3)}`}
      >
        {buckets.map((bucket) => {
          const below = bucket.to <= candidate;
          return (
            <div
              key={bucket.from}
              className={cn(
                "flex-1 rounded-t-sm transition-[height,background-color] duration-200",
                "motion-reduce:transition-none",
                below ? "bg-muted-foreground/25" : "bg-primary/60",
              )}
              style={{
                height: `${Math.max((bucket.count / max) * 100, bucket.count > 0 ? 3 : 0)}%`,
              }}
              title={`${bucket.from.toFixed(2)}–${bucket.to.toFixed(2)}: ${bucket.count}`}
            />
          );
        })}

        <Marker position={current} label="now" muted />
        <Marker position={candidate} label="candidate" />
      </div>
      <div className="text-muted-foreground mt-1 flex justify-between text-[11px] tabular-nums">
        <span>0.0</span>
        <span>0.5</span>
        <span>1.0</span>
      </div>
    </div>
  );
}

function Marker({ position, label, muted }: { position: number; label: string; muted?: boolean }) {
  return (
    <div
      className="pointer-events-none absolute inset-y-0"
      style={{ left: `${position * 100}%` }}
      aria-hidden
    >
      <div className={cn("h-full w-px", muted ? "bg-muted-foreground/40" : "bg-primary")} />
      <span
        className={cn(
          "absolute -top-1 left-1 text-[10px] whitespace-nowrap",
          muted ? "text-muted-foreground" : "text-primary font-medium",
        )}
      >
        {label}
      </span>
    </div>
  );
}

function FlippedSessions({
  examples,
  candidate,
}: {
  examples: {
    id: string;
    subject_external_id: string | null;
    similarity: number;
    original_decision: string;
    simulated_decision: string;
    created_at: string;
  }[];
  candidate: number;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="px-5 py-3.5">
        <h4 className="text-sm font-medium">Sessions that would change</h4>
        <p className="text-muted-foreground mt-0.5 text-xs">
          Closest to the threshold first — those are the decisions that were nearly a coin toss
          either way.
        </p>
      </div>
      <div className="overflow-x-auto border-t">
        <table className="w-full text-sm">
          <caption className="sr-only">
            Verification sessions whose outcome changes at {candidate.toFixed(3)}
          </caption>
          <thead>
            <tr className="text-muted-foreground border-b text-left text-xs">
              <th scope="col" className="px-5 py-2.5 font-medium">
                Subject
              </th>
              <th scope="col" className="px-5 py-2.5 text-right font-medium">
                Similarity
              </th>
              <th scope="col" className="px-5 py-2.5 font-medium">
                Change
              </th>
              <th scope="col" className="px-5 py-2.5 text-right font-medium">
                When
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {examples.map((row) => (
              <tr key={row.id} className="hover:bg-accent/40">
                <td className="px-5 py-2.5 font-mono text-xs">{row.subject_external_id ?? "—"}</td>
                <td className="px-5 py-2.5 text-right font-mono text-xs tabular-nums">
                  {row.similarity.toFixed(4)}
                </td>
                <td className="px-5 py-2.5">
                  <span className="flex items-center gap-1.5 text-xs">
                    <Badge
                      variant={row.original_decision === "verified" ? "success" : "destructive"}
                    >
                      {row.original_decision}
                    </Badge>
                    <ArrowRight className="text-muted-foreground size-3" aria-hidden />
                    <Badge
                      variant={row.simulated_decision === "verified" ? "success" : "destructive"}
                    >
                      {row.simulated_decision}
                    </Badge>
                  </span>
                </td>
                <td className="text-muted-foreground px-5 py-2.5 text-right text-xs whitespace-nowrap">
                  {relativeTime(row.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
