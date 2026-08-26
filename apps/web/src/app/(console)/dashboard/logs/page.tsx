"use client";

import * as React from "react";
import { useQueryState } from "nuqs";
import { CircleCheck, CircleX, Download, ScrollText } from "lucide-react";

import { PageHeader } from "@/components/console/page-header";
import { EmptyState, ErrorState } from "@/components/console/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuditLog, useAuthLog } from "@/features/analytics/api";
import { absoluteTime, downloadCsv, relativeTime, toCsv } from "@/lib/format";

export default function LogsPage() {
  const [tab, setTab] = useQueryState("tab", { defaultValue: "audit" });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Logs"
        description="Append-only records of what changed and who signed in."
      />

      <Tabs value={tab ?? "audit"} onValueChange={(value) => void setTab(value)}>
        <TabsList>
          <TabsTrigger value="audit">Audit</TabsTrigger>
          <TabsTrigger value="auth">Authentication</TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === "auth" ? <AuthLogTable /> : <AuditLogTable />}
    </div>
  );
}

function AuditLogTable() {
  const [cursor, setCursor] = useQueryState("cursor");
  const query = useAuditLog({ cursor: cursor ?? undefined });
  const rows = query.data?.data ?? [];

  function exportCsv() {
    downloadCsv(
      `fvas-audit-${new Date().toISOString().slice(0, 10)}.csv`,
      toCsv(
        rows.map((row) => ({ ...row, changes: JSON.stringify(row.changes ?? {}) })),
        [
          "id",
          "created_at",
          "actor_type",
          "actor_email",
          "action",
          "resource_type",
          "resource_id",
          "changes",
          "ip_address",
          "request_id",
        ],
      ),
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b px-5 py-3">
        <p className="text-muted-foreground text-sm">
          Every mutating action. Written in the same transaction as the change it records.
        </p>
        <Button variant="outline" size="sm" onClick={exportCsv} disabled={rows.length === 0}>
          <Download /> Export
        </Button>
      </div>

      {query.isError ? (
        <div className="p-5">
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </div>
      ) : query.isLoading ? (
        <LogSkeleton />
      ) : rows.length === 0 ? (
        <div className="p-5">
          <EmptyState
            icon={ScrollText}
            title="No activity recorded"
            description="Changes to settings, members, keys, and subjects appear here as they happen."
          />
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Audit log</caption>
              <thead>
                <tr className="text-muted-foreground border-b text-left text-xs">
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Action
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Actor
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Resource
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Changes
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    IP
                  </th>
                  <th scope="col" className="px-5 py-2.5 text-right font-medium">
                    Time
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((row) => (
                  <tr key={row.id} className="hover:bg-accent/40 align-top">
                    <td className="px-5 py-2.5">
                      <code className="bg-muted rounded px-1.5 py-0.5 font-mono text-xs">
                        {row.action}
                      </code>
                    </td>
                    <td className="px-5 py-2.5 text-xs">{row.actor_email ?? row.actor_type}</td>
                    <td className="text-muted-foreground px-5 py-2.5 text-xs">
                      {row.resource_type}
                    </td>
                    <td className="text-muted-foreground max-w-xs px-5 py-2.5 font-mono text-[11px]">
                      {row.changes ? (
                        <span className="line-clamp-2 break-all">
                          {JSON.stringify(row.changes)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="text-muted-foreground px-5 py-2.5 font-mono text-xs">
                      {row.ip_address ?? "—"}
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
          <Pager
            count={rows.length}
            cursor={cursor}
            hasMore={query.data?.pagination.has_more ?? false}
            nextCursor={query.data?.pagination.next_cursor ?? null}
            onCursor={(value) => void setCursor(value)}
          />
        </>
      )}
    </Card>
  );
}

function AuthLogTable() {
  const [cursor, setCursor] = useQueryState("cursor");
  const query = useAuthLog({ cursor: cursor ?? undefined });
  const rows = query.data?.data ?? [];

  return (
    <Card className="overflow-hidden">
      <div className="border-b px-5 py-3">
        <p className="text-muted-foreground text-sm">
          Sign-ins, failures, and token events for members of this organization.
        </p>
      </div>

      {query.isError ? (
        <div className="p-5">
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        </div>
      ) : query.isLoading ? (
        <LogSkeleton />
      ) : rows.length === 0 ? (
        <div className="p-5">
          <EmptyState
            icon={ScrollText}
            title="No authentication events"
            description="Sign-ins and token activity for your members will appear here."
          />
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Authentication log</caption>
              <thead>
                <tr className="text-muted-foreground border-b text-left text-xs">
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Event
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Email
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Result
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    IP
                  </th>
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    Detail
                  </th>
                  <th scope="col" className="px-5 py-2.5 text-right font-medium">
                    Time
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((row) => (
                  <tr key={row.id} className="hover:bg-accent/40">
                    <td className="px-5 py-2.5">
                      <code className="bg-muted rounded px-1.5 py-0.5 font-mono text-xs">
                        {row.event}
                      </code>
                    </td>
                    <td className="px-5 py-2.5 text-xs">{row.email ?? "—"}</td>
                    <td className="px-5 py-2.5">
                      {/* Icon plus colour, so the outcome survives grayscale. */}
                      {row.success ? (
                        <Badge variant="success">
                          <CircleCheck aria-hidden /> success
                        </Badge>
                      ) : (
                        <Badge variant="destructive">
                          <CircleX aria-hidden /> failed
                        </Badge>
                      )}
                    </td>
                    <td className="text-muted-foreground px-5 py-2.5 font-mono text-xs">
                      {row.ip_address ?? "—"}
                    </td>
                    <td className="text-muted-foreground px-5 py-2.5 text-xs">
                      {row.detail ?? "—"}
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
          <Pager
            count={rows.length}
            cursor={cursor}
            hasMore={query.data?.pagination.has_more ?? false}
            nextCursor={query.data?.pagination.next_cursor ?? null}
            onCursor={(value) => void setCursor(value)}
          />
        </>
      )}
    </Card>
  );
}

function Pager({
  count,
  cursor,
  hasMore,
  nextCursor,
  onCursor,
}: {
  count: number;
  cursor: string | null;
  hasMore: boolean;
  nextCursor: string | null;
  onCursor: (cursor: string | null) => void;
}) {
  return (
    <div className="flex items-center justify-between border-t px-5 py-3">
      <p className="text-muted-foreground text-xs">
        Showing {count} entr{count === 1 ? "y" : "ies"}
      </p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={!cursor} onClick={() => onCursor(null)}>
          First page
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!hasMore}
          onClick={() => onCursor(nextCursor)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

function LogSkeleton() {
  return (
    <div className="divide-y">
      {Array.from({ length: 8 }, (_, index) => (
        <div key={index} className="flex items-center gap-4 px-5 py-3">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="ml-auto h-4 w-20" />
        </div>
      ))}
    </div>
  );
}
