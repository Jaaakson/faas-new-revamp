import { cn } from "@/lib/utils";

/**
 * Loading placeholder.
 *
 * Skeletons must match the geometry of what replaces them, or the page jumps
 * when data arrives — cumulative layout shift that a spinner would at least
 * have been honest about. Callers size these to the real content, never to a
 * generic block.
 */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("bg-muted animate-pulse rounded-md", className)}
      // Decorative: the loading state is announced once by the region that
      // owns it, not by every shimmer inside it.
      aria-hidden
      {...props}
    />
  );
}

export { Skeleton };
