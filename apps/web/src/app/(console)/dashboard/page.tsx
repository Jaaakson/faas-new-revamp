"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowRight, KeyRound, ScanFace, TriangleAlert, UserRoundPlus } from "lucide-react";

import { VolumeChart } from "@/components/console/charts";
import { DecisionBadge, SimilarityBar } from "@/components/console/decision";
import { MetricCard, MetricCardSkeleton } from "@/components/console/metric-card";
import { PageHeader } from "@/components/console/page-header";
import { EmptyState, ErrorState } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useOverview, useTimeseries, useVerifications } from "@/features/analytics/api";
import { relativeTime } from "@/lib/format";
import { useAuthStore } from "@/stores/auth-store";

const RANGES = [
  { value: "7", label: "7 days" },
  { value: "14", label: "14 days" },
  { value: "30", label: "30 days" },
];

export default function OverviewPage() {
  const [range, setRange] = React.useState("7");
  const days = Number(range);

  const user = useAuthStore((state) => state.user);
  const organization = useAuthStore((state) => state.organization);

  const overview = useOverview(days);
  const timeseries = useTimeseries(30);
  const recent = useVerifications({ limit: 8 });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overview"
        description={`Everything happening in ${organization?.name ?? "your organization"}`}
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

      {user && !user.email_verified ? (
        <div className="border-warning/30 bg-warning/5 flex gap-3 rounded-lg border p-4">
          <TriangleAlert className="text-warning mt-0.5 size-4 shrink-0" aria-hidden />
          <div className="text-sm">
            <p className="font-medium">Verify your email</p>
            <p className="text-muted-foreground mt-1 leading-relaxed">
              Live API keys require a verified address, so we can reach you if a key ever needs
              revoking.
            </p>
          </div>
        </div>
      ) : null}

      {/* ── Metrics ────────────────────────────────────────────────────────── */}
      {overview.isError ? (
        // Only the failing region degrades. A broken metric call must not take
        // down the chart and the table below it.
        <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
      ) : overview.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <MetricCardSkeleton key={index} />
          ))}
        </div>
      ) : overview.data && !overview.data.has_any_data ? (
        <EmptyState
          icon={ScanFace}
          title="No verifications yet"
          description="Run your first verification and it will appear here within seconds, with its score, threshold, and latency."
          action={
            <Button asChild>
              <Link href="/docs/quickstart">
                Read the quickstart <ArrowRight />
              </Link>
            </Button>
          }
          docsHref="/docs/verification"
        />
      ) : overview.data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard label="Verifications" metric={overview.data.verifications} />
          <MetricCard
            label="Success rate"
            metric={overview.data.success_rate}
            format={(value) => value.toFixed(1)}
            suffix="%"
          />
          <MetricCard
            label="p95 latency"
            metric={overview.data.p95_latency_ms}
            format={(value) => Math.round(value).toLocaleString()}
            suffix="ms"
          />
          <MetricCard label="Active subjects" metric={overview.data.active_subjects} />
        </div>
      ) : null}

      {/* ── Chart + quick actions ──────────────────────────────────────────── */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <div className="flex items-baseline justify-between">
            <h2 className="font-medium">Verification volume</h2>
            <span className="text-muted-foreground text-xs">Last 30 days</span>
          </div>

          <div className="mt-4">
            {timeseries.isError ? (
              <ErrorState error={timeseries.error} onRetry={() => void timeseries.refetch()} />
            ) : timeseries.isLoading ? (
              // Same height as the chart, so nothing jumps when it resolves.
              <Skeleton className="h-[260px] w-full" />
            ) : (
              <VolumeChart data={timeseries.data ?? []} />
            )}
          </div>

          <div className="text-muted-foreground mt-3 flex flex-wrap gap-4 text-xs">
            <Legend color="bg-chart-2" label="Verified" />
            <Legend color="bg-chart-4" label="Rejected" />
            <Legend color="bg-chart-3" label="Inconclusive" />
          </div>
        </Card>

        <Card className="p-5">
          <h2 className="font-medium">Quick actions</h2>
          <div className="mt-4 space-y-2">
            <QuickAction
              icon={ScanFace}
              label="View verifications"
              href="/dashboard/verifications"
            />
            <QuickAction icon={UserRoundPlus} label="Browse subjects" href="/dashboard/subjects" />
            <QuickAction
              icon={KeyRound}
              label="Invite a member"
              href="/dashboard/settings/members"
            />
          </div>

          <div className="mt-6 border-t pt-4">
            <h3 className="text-sm font-medium">Integrating?</h3>
            <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
              The quickstart takes you from a test key to a verified response in about ten minutes.
            </p>
            <Button variant="outline" size="sm" className="mt-3 w-full" asChild>
              <Link href="/docs/quickstart">Open the quickstart</Link>
            </Button>
          </div>
        </Card>
      </div>

      {/* ── Recent verifications ───────────────────────────────────────────── */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h2 className="font-medium">Recent verifications</h2>
          <Button variant="ghost" size="sm" asChild>
            <Link href="/dashboard/verifications">
              View all <ArrowRight />
            </Link>
          </Button>
        </div>

        {recent.isError ? (
          <div className="p-5">
            <ErrorState error={recent.error} onRetry={() => void recent.refetch()} />
          </div>
        ) : recent.isLoading ? (
          <div className="divide-y">
            {Array.from({ length: 6 }, (_, index) => (
              <div key={index} className="flex items-center gap-4 px-5 py-3">
                <Skeleton className="h-4 w-16" />
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-20" />
                <Skeleton className="ml-auto h-4 w-16" />
              </div>
            ))}
          </div>
        ) : (recent.data?.data.length ?? 0) === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={ScanFace}
              title="Nothing here yet"
              description="Verification results appear here in real time as your integration starts sending requests."
              docsHref="/docs/quickstart"
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Eight most recent verification sessions</caption>
              <thead>
                <tr className="text-muted-foreground border-b text-left text-xs">
                  <th scope="col" className="px-5 py-2 font-medium">
                    Time
                  </th>
                  <th scope="col" className="px-5 py-2 font-medium">
                    Subject
                  </th>
                  <th scope="col" className="px-5 py-2 font-medium">
                    Decision
                  </th>
                  <th scope="col" className="px-5 py-2 font-medium">
                    Score
                  </th>
                  <th scope="col" className="px-5 py-2 text-right font-medium">
                    Latency
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {recent.data?.data.map((row) => (
                  <tr key={row.id} className="hover:bg-accent/40">
                    <td className="text-muted-foreground px-5 py-2.5 whitespace-nowrap">
                      <time
                        dateTime={row.created_at}
                        title={new Date(row.created_at).toLocaleString()}
                      >
                        {relativeTime(row.created_at)}
                      </time>
                    </td>
                    <td className="px-5 py-2.5 font-mono text-xs">
                      {row.subject_id ? `${row.subject_id.slice(0, 14)}…` : "—"}
                    </td>
                    <td className="px-5 py-2.5">
                      <DecisionBadge decision={row.decision} />
                    </td>
                    <td className="px-5 py-2.5">
                      <SimilarityBar
                        similarity={row.similarity}
                        threshold={row.threshold_applied}
                        decision={row.decision}
                      />
                    </td>
                    <td className="px-5 py-2.5 text-right font-mono text-xs tabular-nums">
                      {row.latency_ms}ms
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`size-2 rounded-full ${color}`} aria-hidden />
      {label}
    </span>
  );
}

function QuickAction({
  icon: Icon,
  label,
  href,
}: {
  icon: React.ElementType;
  label: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="hover:bg-accent focus-visible:ring-ring flex items-center gap-2.5 rounded-md px-2 py-2 text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none"
    >
      <Icon className="text-muted-foreground size-4" aria-hidden />
      <span className="flex-1">{label}</span>
      <ArrowRight className="text-muted-foreground size-3.5" aria-hidden />
    </Link>
  );
}
