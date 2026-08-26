import * as React from "react";
import { CircleAlert, Info, Lightbulb, TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

const VARIANTS = {
  info: { icon: Info, className: "border-info/30 bg-info/5", iconClass: "text-info" },
  tip: {
    icon: Lightbulb,
    className: "border-success/30 bg-success/5",
    iconClass: "text-success",
  },
  warning: {
    icon: TriangleAlert,
    className: "border-warning/30 bg-warning/5",
    iconClass: "text-warning",
  },
  danger: {
    icon: CircleAlert,
    className: "border-destructive/30 bg-destructive/5",
    iconClass: "text-destructive",
  },
} as const;

/**
 * Docs callout. Available inside MDX without an import.
 *
 * Each variant pairs a color with a distinct icon so the severity survives
 * color-vision deficiency and grayscale printing.
 */
export function Callout({
  variant = "info",
  title,
  children,
}: {
  variant?: keyof typeof VARIANTS;
  title?: string;
  children: React.ReactNode;
}) {
  const { icon: Icon, className, iconClass } = VARIANTS[variant];

  return (
    <div className={cn("mt-6 flex gap-3 rounded-lg border p-4", className)}>
      <Icon className={cn("mt-0.5 size-4 shrink-0", iconClass)} aria-hidden />
      <div className="min-w-0 text-sm">
        {title ? <p className="text-foreground font-medium">{title}</p> : null}
        <div className="text-muted-foreground [&>p]:mt-1 [&>p:first-child]:mt-0">{children}</div>
      </div>
    </div>
  );
}
