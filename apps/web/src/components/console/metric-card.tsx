"use client";

import { TrendingDown, TrendingUp } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export interface MetricDelta {
  value: number;
  previous: number;
  change_pct: number | null;
  higher_is_better: boolean;
}

/**
 * A headline number with its period-over-period change.
 *
 * The delta is the point. "12,481 verifications" is a fact; "12,481, up 12.4%"
 * is a reason to act or not. `higher_is_better` exists because the same arrow
 * means opposite things for volume and for latency — the card cannot infer it.
 */
export function MetricCard({
  label,
  metric,
  format = (value) => value.toLocaleString(),
  suffix,
}: {
  label: string;
  metric: MetricDelta;
  format?: (value: number) => string;
  suffix?: string;
}) {
  const change = metric.change_pct;
  const rose = change !== null && change > 0;
  // Good/bad, not up/down. Latency rising is bad; volume rising is good.
  const good = change === null || change === 0 ? null : rose === metric.higher_is_better;

  return (
    <Card className="p-5">
      <p className="text-muted-foreground text-sm">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">
        {format(metric.value)}
        {suffix ? <span className="text-muted-foreground ml-1 text-base">{suffix}</span> : null}
      </p>

      <div className="mt-2 flex items-center gap-1.5 text-xs">
        {change === null ? (
          // No baseline. Showing "+0%" here would be a fabrication.
          <span className="text-muted-foreground">No prior period</span>
        ) : (
          <>
            <span
              className={cn(
                "inline-flex items-center gap-0.5 font-medium tabular-nums",
                good === null
                  ? "text-muted-foreground"
                  : good
                    ? "text-success"
                    : "text-destructive",
              )}
            >
              {rose ? (
                <TrendingUp className="size-3.5" aria-hidden />
              ) : (
                <TrendingDown className="size-3.5" aria-hidden />
              )}
              {Math.abs(change)}%
            </span>
            <span className="text-muted-foreground">vs previous period</span>
          </>
        )}
      </div>
    </Card>
  );
}

export function MetricCardSkeleton() {
  // Mirrors the real card's geometry so nothing shifts when data arrives.
  return (
    <Card className="p-5">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="mt-3 h-8 w-32" />
      <Skeleton className="mt-3 h-3 w-40" />
    </Card>
  );
}
