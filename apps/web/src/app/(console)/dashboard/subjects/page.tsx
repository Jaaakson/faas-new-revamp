"use client";

import * as React from "react";
import Link from "next/link";
import { useQueryState } from "nuqs";
import { Plus, Search, UserRound } from "lucide-react";

import { CreateSubjectDialog } from "@/components/console/create-subject-dialog";
import { PageHeader } from "@/components/console/page-header";
import { EmptyState, ErrorState, NoResultsState } from "@/components/console/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useSubjects } from "@/features/analytics/api";
import { absoluteTime, relativeTime } from "@/lib/format";

const STATUSES = [
  { value: "all", label: "All" },
  { value: "enrolled", label: "Enrolled" },
  { value: "pending", label: "Pending" },
  { value: "suspended", label: "Suspended" },
];

const STATUS_VARIANT = {
  enrolled: "success",
  pending: "warning",
  suspended: "secondary",
} as const;

export default function SubjectsPage() {
  const [status, setStatus] = useQueryState("status", { defaultValue: "all" });
  const [search, setSearch] = useQueryState("q");
  const [cursor, setCursor] = useQueryState("cursor");
  const [creating, setCreating] = React.useState(false);

  // Debounced so typing does not fire a request per keystroke.
  const [draft, setDraft] = React.useState(search ?? "");
  React.useEffect(() => {
    const timer = setTimeout(() => {
      void setSearch(draft || null);
      void setCursor(null);
    }, 300);
    return () => clearTimeout(timer);
  }, [draft, setSearch, setCursor]);

  const query = useSubjects({
    status: status === "all" ? undefined : (status ?? undefined),
    search: search ?? undefined,
    cursor: cursor ?? undefined,
    limit: 20,
  });

  const rows = query.data?.data ?? [];
  const filtered = status !== "all" || !!search || !!cursor;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Subjects"
        description="The end users you verify. Identified by your own external ID, never ours."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" aria-hidden />
            New subject
          </Button>
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1 sm:max-w-xs">
          <Search
            className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2"
            aria-hidden
          />
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Search by external ID…"
            className="pl-8"
            aria-label="Search subjects by external ID"
          />
        </div>

        <Tabs
          value={status ?? "all"}
          onValueChange={(value) => {
            void setStatus(value === "all" ? null : value);
            void setCursor(null);
          }}
        >
          <TabsList>
            {STATUSES.map((option) => (
              <TabsTrigger key={option.value} value={option.value}>
                {option.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <Card className="overflow-hidden">
        {query.isError ? (
          <div className="p-5">
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          </div>
        ) : query.isLoading ? (
          <div className="divide-y">
            {Array.from({ length: 8 }, (_, index) => (
              <div key={index} className="flex items-center gap-4 px-5 py-3">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-5 w-20 rounded-full" />
                <Skeleton className="ml-auto h-4 w-16" />
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <div className="p-5">
            {filtered ? (
              <NoResultsState
                onClear={() => {
                  setDraft("");
                  void setStatus(null);
                  void setSearch(null);
                  void setCursor(null);
                }}
              />
            ) : (
              <EmptyState
                icon={UserRound}
                title="No subjects yet"
                description="A subject is one of your end users. Create one here or through the API, then enroll their face."
                docsHref="/docs/enrollment"
                action={
                  <Button size="sm" onClick={() => setCreating(true)}>
                    <Plus className="size-3.5" aria-hidden />
                    New subject
                  </Button>
                }
              />
            )}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Subjects</caption>
                <thead>
                  <tr className="text-muted-foreground border-b text-left text-xs">
                    <th scope="col" className="px-5 py-2.5 font-medium">
                      External ID
                    </th>
                    <th scope="col" className="px-5 py-2.5 font-medium">
                      Name
                    </th>
                    <th scope="col" className="px-5 py-2.5 font-medium">
                      Status
                    </th>
                    <th scope="col" className="px-5 py-2.5 text-right font-medium">
                      Verifications
                    </th>
                    <th scope="col" className="px-5 py-2.5 text-right font-medium">
                      Enrolled
                    </th>
                    <th scope="col" className="px-5 py-2.5 text-right font-medium">
                      Last verified
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {rows.map((row) => (
                    <tr key={row.id} className="hover:bg-accent/40">
                      <td className="px-5 py-2.5 font-mono text-xs">
                        <Link
                          href={`/dashboard/subjects/${row.id}`}
                          className="hover:text-primary underline-offset-2 hover:underline"
                        >
                          {row.external_id}
                        </Link>
                      </td>
                      <td className="px-5 py-2.5">{row.display_name ?? "—"}</td>
                      <td className="px-5 py-2.5">
                        <Badge
                          variant={
                            STATUS_VARIANT[row.status as keyof typeof STATUS_VARIANT] ?? "outline"
                          }
                        >
                          {row.status}
                        </Badge>
                      </td>
                      <td className="px-5 py-2.5 text-right font-mono text-xs tabular-nums">
                        {row.verification_count.toLocaleString()}
                      </td>
                      <td className="text-muted-foreground px-5 py-2.5 text-right text-xs whitespace-nowrap">
                        {row.enrolled_at ? (
                          <time dateTime={row.enrolled_at} title={absoluteTime(row.enrolled_at)}>
                            {relativeTime(row.enrolled_at)}
                          </time>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="text-muted-foreground px-5 py-2.5 text-right text-xs whitespace-nowrap">
                        {row.last_verified_at ? (
                          <time
                            dateTime={row.last_verified_at}
                            title={absoluteTime(row.last_verified_at)}
                          >
                            {relativeTime(row.last_verified_at)}
                          </time>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between border-t px-5 py-3">
              <p className="text-muted-foreground text-xs">
                Showing {rows.length} subject{rows.length === 1 ? "" : "s"}
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

      <CreateSubjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
