"use client";

import * as React from "react";
import { useQueryState } from "nuqs";
import { Download, ScanFace } from "lucide-react";

import { ConfidenceBadge, DecisionBadge, SimilarityBar } from "@/components/console/decision";
import { PageHeader } from "@/components/console/page-header";
import { EmptyState, ErrorState, NoResultsState } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useVerifications } from "@/features/analytics/api";
import { absoluteTime, downloadCsv, relativeTime, toCsv } from "@/lib/format";

const DECISIONS = [
  { value: "all", label: "All" },
  { value: "verified", label: "Verified" },
  { value: "rejected", label: "Rejected" },
  { value: "inconclusive", label: "Inconclusive" },
];

export default function VerificationsPage() {
  // Filters live in the URL, so a compliance officer sends a colleague a link
  // rather than a screenshot, and the back button behaves.
  const [decision, setDecision] = useQueryState("decision", { defaultValue: "all" });
  const [cursor, setCursor] = useQueryState("cursor");

  const filters = {
    decision: decision === "all" ? undefined : decision,
    cursor: cursor ?? undefined,
    limit: 20,
  };
  const query = useVerifications(filters);

  const rows = query.data?.data ?? [];
  const filtered = decision !== "all" || !!cursor;

  function exportCsv() {
    downloadCsv(
      `fvas-verifications-${new Date().toISOString().slice(0, 10)}.csv`,
      toCsv(rows as unknown as Record<string, unknown>[], [
        "id",
        "created_at",
        "subject_id",
        "decision",
        "similarity",
        "threshold_applied",
        "confidence",
        "failure_reason",
        "latency_ms",
        "source",
      ]),
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Verification sessions"
        description="Every attempt, including failures — failure rates are a product signal."
        actions={
          <Button variant="outline" size="sm" onClick={exportCsv} disabled={rows.length === 0}>
            <Download /> Export CSV
          </Button>
        }
      />

      <Tabs
        value={decision ?? "all"}
        onValueChange={(value) => {
          void setDecision(value === "all" ? null : value);
          // A cursor from the previous filter points into a different result
          // set; keeping it would silently skip rows.
          void setCursor(null);
        }}
      >
        <TabsList>
          {DECISIONS.map((option) => (
            <TabsTrigger key={option.value} value={option.value}>
              {option.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <Card className="overflow-hidden">
        {query.isError ? (
          <div className="p-5">
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          </div>
        ) : query.isLoading ? (
          <TableSkeleton />
        ) : rows.length === 0 ? (
          <div className="p-5">
            {filtered ? (
              <NoResultsState
                onClear={() => {
                  void setDecision(null);
                  void setCursor(null);
                }}
              />
            ) : (
              <EmptyState
                icon={ScanFace}
                title="No verifications yet"
                description="Sessions appear here the moment your integration sends its first request."
                docsHref="/docs/quickstart"
              />
            )}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Verification sessions</caption>
                <thead>
                  <tr className="text-muted-foreground border-b text-left text-xs">
                    <th scope="col" className="px-5 py-2.5 font-medium">
                      Session
                    </th>
                    <th scope="col" className="px-5 py-2.5 font-medium">
                      Subject
                    </th>
                    <th scope="col" className="px-5 py-2.5 font-medium">
                      Decision
                    </th>
                    <th scope="col" className="px-5 py-2.5 font-medium">
                      Score
                    </th>
                    <th scope="col" className="px-5 py-2.5 font-medium">
                      Reason
                    </th>
                    <th scope="col" className="px-5 py-2.5 font-medium">
                      Source
                    </th>
                    <th scope="col" className="px-5 py-2.5 text-right font-medium">
                      Latency
                    </th>
                    <th scope="col" className="px-5 py-2.5 text-right font-medium">
                      Time
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {rows.map((row) => (
                    <tr key={row.id} className="hover:bg-accent/40">
                      <td className="px-5 py-2.5 font-mono text-xs">{row.id.slice(0, 16)}…</td>
                      <td className="px-5 py-2.5 font-mono text-xs">
                        {row.subject_id ? `${row.subject_id.slice(0, 14)}…` : "—"}
                      </td>
                      <td className="px-5 py-2.5">
                        <div className="flex items-center gap-2">
                          <DecisionBadge decision={row.decision} />
                          <ConfidenceBadge confidence={row.confidence} />
                        </div>
                      </td>
                      <td className="px-5 py-2.5">
                        <SimilarityBar
                          similarity={row.similarity}
                          threshold={row.threshold_applied}
                          decision={row.decision}
                        />
                      </td>
                      <td className="text-muted-foreground px-5 py-2.5 font-mono text-xs">
                        {row.failure_reason ?? "—"}
                      </td>
                      <td className="text-muted-foreground px-5 py-2.5 text-xs">{row.source}</td>
                      <td className="px-5 py-2.5 text-right font-mono text-xs tabular-nums">
                        {row.latency_ms}ms
                      </td>
                      <td className="text-muted-foreground px-5 py-2.5 text-right text-xs whitespace-nowrap">
                        <time dateTime={row.created_at} title={absoluteTime(row.created_at)}>
                          {relativeTime(row.created_at)}
                        </time>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between border-t px-5 py-3">
              <p className="text-muted-foreground text-xs">
                Showing {rows.length} session{rows.length === 1 ? "" : "s"}
              </p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!cursor}
                  onClick={() => void setCursor(null)}
                >
                  First page
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!query.data?.pagination.has_more}
                  onClick={() => void setCursor(query.data?.pagination.next_cursor ?? null)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="divide-y">
      {Array.from({ length: 10 }, (_, index) => (
        <div key={index} className="flex items-center gap-4 px-5 py-3">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-5 w-20 rounded-full" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="ml-auto h-4 w-16" />
        </div>
      ))}
    </div>
  );
}
