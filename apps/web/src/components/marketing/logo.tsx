import Link from "next/link";
import { ScanFace } from "lucide-react";

import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <Link
      href="/"
      className={cn(
        "focus-visible:ring-ring flex items-center gap-2 rounded-md focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none",
        className,
      )}
      aria-label="Fvas — home"
    >
      <ScanFace className="text-primary size-5" aria-hidden />
      <span className="text-[15px] font-semibold tracking-tight">Fvas</span>
    </Link>
  );
}
