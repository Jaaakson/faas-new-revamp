"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";

import { docsNeighbours } from "@/config/docs";

/**
 * Previous/next links derived from the docs nav order.
 *
 * Docs are written to be read in sequence; without a pager a reader has to
 * return to the sidebar after every page and remember where they were.
 */
export function DocsPager() {
  const pathname = usePathname();
  const { previous, next } = docsNeighbours(pathname);

  if (!previous && !next) return null;

  return (
    <nav
      aria-label="Documentation pages"
      className="mt-16 flex flex-col gap-3 border-t pt-6 sm:flex-row sm:justify-between"
    >
      {previous ? (
        <Link
          href={previous.href}
          className="hover:bg-accent focus-visible:ring-ring group flex flex-1 items-center gap-3 rounded-lg border p-4 transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          <ArrowLeft className="text-muted-foreground size-4 shrink-0" aria-hidden />
          <span className="min-w-0">
            <span className="text-muted-foreground block text-xs">Previous</span>
            <span className="block truncate text-sm font-medium">{previous.title}</span>
          </span>
        </Link>
      ) : (
        <div className="flex-1" />
      )}

      {next ? (
        <Link
          href={next.href}
          className="hover:bg-accent focus-visible:ring-ring group flex flex-1 items-center justify-end gap-3 rounded-lg border p-4 text-right transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          <span className="min-w-0">
            <span className="text-muted-foreground block text-xs">Next</span>
            <span className="block truncate text-sm font-medium">{next.title}</span>
          </span>
          <ArrowRight className="text-muted-foreground size-4 shrink-0" aria-hidden />
        </Link>
      ) : (
        <div className="flex-1" />
      )}
    </nav>
  );
}
