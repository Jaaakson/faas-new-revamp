"use client";

import * as React from "react";
import Link from "next/link";
import { CircleAlert, Inbox, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";

/**
 * The four states every data-bearing surface must implement.
 *
 * This is a checklist enforced in review, not an aspiration — a page that
 * renders a bare spinner or a blank div has shipped three missing screens.
 */

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  docsHref,
  className,
}: {
  icon?: React.ElementType;
  title: string;
  description: string;
  action?: React.ReactNode;
  docsHref?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-16 text-center",
        className,
      )}
    >
      <div className="bg-muted flex size-11 items-center justify-center rounded-full">
        <Icon className="text-muted-foreground size-5" aria-hidden />
      </div>
      <h3 className="mt-4 font-medium">{title}</h3>
      <p className="text-muted-foreground mt-1.5 max-w-sm text-sm leading-relaxed">{description}</p>
      {action || docsHref ? (
        <div className="mt-5 flex items-center gap-3">
          {action}
          {docsHref ? (
            <Button variant="ghost" size="sm" asChild>
              <Link href={docsHref}>Read the docs</Link>
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Filtered-to-zero is a *different* state from never-had-data.
 *
 * Conflating them is disorienting: a user who just applied three filters is
 * told they have no subjects at all, and offered an onboarding CTA they do not
 * need. This one offers the action that actually helps — clearing the filters.
 */
export function NoResultsState({ onClear }: { onClear?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-12 text-center">
      <h3 className="font-medium">No results match these filters</h3>
      <p className="text-muted-foreground mt-1.5 text-sm">
        Try widening the date range or clearing a filter.
      </p>
      {onClear ? (
        <Button variant="outline" size="sm" className="mt-4" onClick={onClear}>
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const apiError = error instanceof ApiError ? error : null;

  return (
    <div
      className={cn(
        "border-destructive/30 bg-destructive/5 rounded-lg border px-6 py-10 text-center",
        className,
      )}
      role="alert"
    >
      <CircleAlert className="text-destructive mx-auto size-6" aria-hidden />
      <h3 className="mt-3 font-medium">Couldn&apos;t load this</h3>
      <p className="text-muted-foreground mx-auto mt-1.5 max-w-sm text-sm leading-relaxed">
        {apiError?.message ?? "Something went wrong. This is usually temporary."}
      </p>
      {onRetry ? (
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
          <RotateCw /> Try again
        </Button>
      ) : null}
      {apiError?.requestId ? (
        // A support ticket carrying this ID resolves in one query instead of a
        // conversation, so it is surfaced rather than buried in a console log.
        <p className="text-muted-foreground mt-4 font-mono text-xs">
          Request ID: {apiError.requestId}
        </p>
      ) : null}
    </div>
  );
}
