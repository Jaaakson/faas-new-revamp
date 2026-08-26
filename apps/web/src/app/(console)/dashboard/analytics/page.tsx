"use client";

import * as React from "react";

import {
  FailureReasonBars,
  HourlyHeatmap,
  LatencyHistogram,
  OutcomeDonut,
  VolumeChart,
} from "@/components/console/charts";
import { PageHeader } from "@/components/console/page-header";
import { ErrorState } from "@/components/console/states";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useFailureReasons,
  useHourly,
  useLatency,
  useOutcomes,
  useTimeseries,
} from "@/features/analytics/api";

const RANGES = [
  { value: "7", label: "7d" },
  { value: "30", label: "30d" },
  { value: "90", label: "90d" },
];

export default function AnalyticsPage() {
  const [range, setRange] = React.useState("30");
  const days = Number(range);

  const timeseries = useTimeseries(days);
  const outcomes = useOutcomes(days);
  const failures = useFailureReasons(days);
  const latency = useLatency(days);
  const hourly = useHourly(days);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics"
        description="How verification is performing, and where it is not."
        actions={
          <Tabs value={range} onValueChange={setRange}>
            <TabsList>
              {RANGES.map((option) => (
                <TabsTrigger key={option.value} value={option.value}>
                  {option.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
      />

      <Panel
        title="Verification volume"
        query={timeseries}
        skeletonHeight={260}
        render={(data) => <VolumeChart data={data} />}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Outcome split"
          description="Errors are ours, not a customer outcome — they are excluded from success rate."
          query={outcomes}
          skeletonHeight={220}
          render={(data) => <OutcomeDonut data={data} />}
        />
        <Panel
          title="Failure reasons"
          description="Capture problems and genuine rejections are different signals."
          query={failures}
          skeletonHeight={220}
          render={(data) => <FailureReasonBars data={data} />}
        />
      </div>

      <Panel
        title="Latency distribution"
        description="Measured server-side, from request received to decision written."
        query={latency}
        skeletonHeight={240}
        render={(data) => <LatencyHistogram data={data} />}
      />

      <Panel
        title="Success rate by hour"
        description="A night-shift dip is usually lighting in a physical environment, not fraud."
        query={hourly}
        skeletonHeight={220}
        render={(data) => <HourlyHeatmap data={data} />}
      />
    </div>
  );
}

/**
 * One card, all four states.
 *
 * Every panel on this page loads independently, so a single failing endpoint
 * degrades its own card rather than blanking the page.
 */
function Panel<T>({
  title,
  description,
  query,
  skeletonHeight,
  render,
}: {
  title: string;
  description?: string;
  query: {
    data: T | undefined;
    isLoading: boolean;
    isError: boolean;
    error: unknown;
    refetch: () => void;
  };
  skeletonHeight: number;
  render: (data: T) => React.ReactNode;
}) {
  return (
    <Card className="p-5">
      <h2 className="font-medium">{title}</h2>
      {description ? <p className="text-muted-foreground mt-1 text-sm">{description}</p> : null}

      <div className="mt-4">
        {query.isError ? (
          <ErrorState error={query.error} onRetry={query.refetch} />
        ) : query.isLoading ? (
          <Skeleton style={{ height: skeletonHeight }} className="w-full" />
        ) : query.data ? (
          render(query.data)
        ) : null}
      </div>
    </Card>
  );
}
