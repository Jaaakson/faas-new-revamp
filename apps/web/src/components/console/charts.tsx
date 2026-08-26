"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type {
  FailureReason,
  HourlyCell,
  LatencyDistribution,
  OutcomeSlice,
  TimeseriesPoint,
} from "@/features/analytics/api";
import { cn } from "@/lib/utils";

/**
 * Charts read colours from CSS custom properties rather than literals, so a
 * theme switch re-colours every series without a re-render or a second palette.
 */
const CHART = {
  verified: "var(--chart-2)",
  rejected: "var(--chart-4)",
  inconclusive: "var(--chart-3)",
  error: "var(--muted-foreground)",
  primary: "var(--chart-1)",
} as const;

const AXIS = {
  stroke: "var(--muted-foreground)",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

function shortDay(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** Shared tooltip so every chart explains itself the same way. */
function ChartTooltip({
  active,
  payload,
  label,
  formatter,
}: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string;
  formatter?: (value: number) => string;
}) {
  if (!active || !payload?.length) return null;

  return (
    <div className="bg-popover rounded-lg border px-3 py-2 text-xs shadow-lg">
      {label ? <p className="mb-1.5 font-medium">{label}</p> : null}
      {payload.map((entry) => (
        <p key={entry.name} className="flex items-center gap-2">
          <span
            className="size-2 shrink-0 rounded-full"
            style={{ background: entry.color }}
            aria-hidden
          />
          <span className="text-muted-foreground capitalize">{entry.name}</span>
          <span className="ml-auto font-mono tabular-nums">
            {formatter ? formatter(entry.value) : entry.value.toLocaleString()}
          </span>
        </p>
      ))}
    </div>
  );
}

export function VolumeChart({ data }: { data: TimeseriesPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <defs>
          {(["verified", "rejected", "inconclusive"] as const).map((key) => (
            <linearGradient key={key} id={`fill-${key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART[key]} stopOpacity={0.35} />
              <stop offset="100%" stopColor={CHART[key]} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
        <XAxis dataKey="day" tickFormatter={shortDay} {...AXIS} minTickGap={24} />
        <YAxis {...AXIS} width={44} />
        <Tooltip content={<ChartTooltip />} labelFormatter={(value) => shortDay(String(value))} />
        {/* Stacked, so the top edge reads as total volume while the bands show
            composition — two questions answered by one chart. */}
        <Area
          type="monotone"
          dataKey="verified"
          stackId="1"
          stroke={CHART.verified}
          fill="url(#fill-verified)"
          strokeWidth={1.5}
        />
        <Area
          type="monotone"
          dataKey="rejected"
          stackId="1"
          stroke={CHART.rejected}
          fill="url(#fill-rejected)"
          strokeWidth={1.5}
        />
        <Area
          type="monotone"
          dataKey="inconclusive"
          stackId="1"
          stroke={CHART.inconclusive}
          fill="url(#fill-inconclusive)"
          strokeWidth={1.5}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function OutcomeDonut({ data }: { data: OutcomeSlice[] }) {
  const total = data.reduce((sum, slice) => sum + slice.count, 0);

  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="decision"
            innerRadius={62}
            outerRadius={88}
            paddingAngle={2}
            strokeWidth={0}
          >
            {data.map((slice) => (
              <Cell
                key={slice.decision}
                fill={CHART[slice.decision as keyof typeof CHART] ?? CHART.error}
              />
            ))}
          </Pie>
          <Tooltip content={<ChartTooltip />} />
        </PieChart>
      </ResponsiveContainer>

      {/* Centre label: the total the slices sum to, so the donut is not just
          proportions floating free of a magnitude. */}
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-semibold tabular-nums">{total.toLocaleString()}</span>
        <span className="text-muted-foreground text-xs">total</span>
      </div>
    </div>
  );
}

/**
 * Plain-English gloss for a failure code, shown on hover.
 *
 * The code stays primary: this is a developer console, and `low_quality` is
 * what an integrator greps for in their own logs. The gloss is what makes the
 * list readable to the operations person sitting next to them.
 */
const FAILURE_REASON_LABELS: Record<string, string> = {
  low_quality: "The capture did not meet the quality gates",
  no_face_detected: "No face was found in the frame",
  multiple_faces: "More than one face was visible",
  below_threshold: "A real face, but not this person",
  subject_not_enrolled: "The subject has no active face profile",
  liveness_failed: "The frame looked like a screen or a print",
  model_mismatch: "The profile was built with a different model version",
};

function failureReasonLabel(reason: string): string {
  return FAILURE_REASON_LABELS[reason] ?? reason.replace(/_/g, " ");
}

export function FailureReasonBars({ data }: { data: FailureReason[] }) {
  if (data.length === 0) {
    return (
      <p className="text-muted-foreground py-12 text-center text-sm">No failures in this period.</p>
    );
  }

  const max = Math.max(...data.map((row) => row.count));

  // A horizontal bar list rather than a chart: the labels are long
  // (`subject_not_enrolled`), and rotated axis text is unreadable.
  return (
    <ul className="space-y-3">
      {data.map((row) => (
        <li key={row.reason}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="truncate font-mono text-xs" title={failureReasonLabel(row.reason)}>
              {row.reason}
            </span>
            {/* Parenthesised, not just spaced. Two adjacent numbers separated by
                a 6px margin read as one figure — `23` and `33.8%` rendered as
                "2333.8%" at a glance, and identically to a screen reader. */}
            <span className="text-muted-foreground shrink-0 tabular-nums">
              {row.count.toLocaleString()}
              <span className="ml-1.5 text-xs">({row.percentage}%)</span>
            </span>
          </div>
          <div className="bg-muted mt-1.5 h-1.5 overflow-hidden rounded-full">
            <div
              className="bg-chart-4 h-full rounded-full"
              style={{ width: `${(row.count / max) * 100}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function LatencyHistogram({ data }: { data: LatencyDistribution }) {
  return (
    <>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data.buckets} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="bucket" {...AXIS} />
          <YAxis {...AXIS} width={44} />
          <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--muted)" }} />
          <Bar dataKey="count" fill={CHART.primary} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>

      <dl className="mt-4 grid grid-cols-3 gap-3 border-t pt-4 text-sm">
        {[
          ["p50", data.p50],
          ["p95", data.p95],
          ["p99", data.p99],
        ].map(([label, value]) => (
          <div key={String(label)}>
            <dt className="text-muted-foreground text-xs">{label}</dt>
            <dd className="mt-0.5 font-mono tabular-nums">{value}ms</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/**
 * Success rate by weekday and hour.
 *
 * The chart that produces an insight nobody asked for: a night-shift dip is
 * almost always lighting in a physical environment, not fraud. That turns a
 * support conversation into a product one.
 */
export function HourlyHeatmap({ data }: { data: HourlyCell[] }) {
  const byKey = React.useMemo(() => {
    const map = new Map<string, HourlyCell>();
    for (const cell of data) map.set(`${cell.weekday}-${cell.hour}`, cell);
    return map;
  }, [data]);

  function tone(cell: HourlyCell | undefined): string {
    if (!cell || cell.total === 0) return "bg-muted/40";
    const rate = cell.success_rate ?? 0;
    if (rate >= 97) return "bg-chart-2";
    if (rate >= 92) return "bg-chart-2/70";
    if (rate >= 85) return "bg-chart-4/70";
    if (rate >= 70) return "bg-chart-4";
    return "bg-destructive/80";
  }

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[560px]">
        <div className="flex gap-1 pl-9">
          {Array.from({ length: 24 }, (_, hour) => (
            <span key={hour} className="text-muted-foreground w-4 shrink-0 text-center text-[9px]">
              {hour % 6 === 0 ? hour : ""}
            </span>
          ))}
        </div>

        {WEEKDAYS.map((label, weekday) => (
          <div key={label} className="mt-1 flex items-center gap-1">
            <span className="text-muted-foreground w-8 shrink-0 text-[10px]">{label}</span>
            {Array.from({ length: 24 }, (_, hour) => {
              const cell = byKey.get(`${weekday}-${hour}`);
              return (
                <span
                  key={hour}
                  className={cn("size-4 shrink-0 rounded-[2px]", tone(cell))}
                  // Title rather than a tooltip component: 168 cells, and a
                  // portal per cell would be a lot of DOM for a hover hint.
                  title={
                    cell && cell.total > 0
                      ? `${label} ${hour}:00 — ${cell.success_rate}% of ${cell.total}`
                      : `${label} ${hour}:00 — no traffic`
                  }
                />
              );
            })}
          </div>
        ))}

        <div className="text-muted-foreground mt-4 flex items-center gap-2 text-[10px]">
          <span>Lower</span>
          <span className="bg-destructive/80 size-3 rounded-[2px]" />
          <span className="bg-chart-4 size-3 rounded-[2px]" />
          <span className="bg-chart-4/70 size-3 rounded-[2px]" />
          <span className="bg-chart-2/70 size-3 rounded-[2px]" />
          <span className="bg-chart-2 size-3 rounded-[2px]" />
          <span>Higher success rate</span>
          <span className="bg-muted/40 ml-3 size-3 rounded-[2px]" />
          <span>No traffic</span>
        </div>
      </div>
    </div>
  );
}
