import * as React from "react";

import { Reveal } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

/**
 * Marketing section wrapper: consistent vertical rhythm and max width.
 *
 * Centralizing the spacing scale here is what makes ten sections written at
 * different times read as one page (docs/04-design-system.md §4).
 */
export function Section({
  children,
  className,
  containerClassName,
  id,
}: {
  children: React.ReactNode;
  className?: string;
  containerClassName?: string;
  id?: string;
}) {
  return (
    <section id={id} className={cn("scroll-mt-20 py-20 sm:py-28", className)}>
      <div className={cn("mx-auto max-w-6xl px-6", containerClassName)}>{children}</div>
    </section>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  align = "left",
  className,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  align?: "left" | "center";
  className?: string;
}) {
  return (
    <Reveal className={cn("max-w-2xl", align === "center" && "mx-auto text-center", className)}>
      {eyebrow ? <p className="text-primary text-sm font-medium tracking-wide">{eyebrow}</p> : null}
      <h2
        className={cn("text-3xl font-semibold tracking-tight sm:text-4xl", eyebrow && "mt-2")}
        style={{ letterSpacing: "-0.02em" }}
      >
        {title}
      </h2>
      {description ? <p className="text-muted-foreground mt-4 text-lg">{description}</p> : null}
    </Reveal>
  );
}
