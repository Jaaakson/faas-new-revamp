import * as React from "react";

import { Badge } from "@/components/ui/badge";

/**
 * Consistent header for every non-landing marketing page.
 *
 * A shared component keeps ten pages from each inventing their own top-of-page
 * spacing, which is the fastest way for a site to stop feeling like one product.
 */
export function PageHero({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="border-b">
      <div className="mx-auto max-w-6xl px-6 py-16 sm:py-20">
        {eyebrow ? <Badge variant="outline">{eyebrow}</Badge> : null}
        <h1
          className="mt-4 max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl"
          style={{ letterSpacing: "-0.02em" }}
        >
          {title}
        </h1>
        {description ? (
          <p className="text-muted-foreground mt-5 max-w-2xl text-lg">{description}</p>
        ) : null}
        {children ? <div className="mt-8">{children}</div> : null}
      </div>
    </div>
  );
}
